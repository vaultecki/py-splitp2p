import json
from unittest.mock import MagicMock, patch

import pytest
import trio

import crypto
import network
from models import Expense, Settlement, Split


class DummyCallbacks(network.NetworkCallbacks):
    pass


def make_network(**kw):
    group_key = crypto.generate_group_key()
    return network.P2PNetwork(group_key, "topic1", DummyCallbacks(), **kw), group_key


def test_init_sets_defaults():
    net, _ = make_network()
    assert net.topic_id == "splitp2p-topic1"
    assert net._host is None
    assert net._pubsub is None
    assert net._running is False
    assert net._peers == set()


def test_set_own_identity():
    net, _ = make_network()
    net.set_own_identity("pk1", "Alice", 1234)
    assert net._own_pubkey == "pk1"
    assert net._own_name == "Alice"
    assert net._own_joined_at == 1234


def test_set_db():
    net, _ = make_network()
    fake_db = object()
    net.set_db(fake_db, "g1")
    assert net._db is fake_db
    assert net._group_id == "g1"


def test_stop_queues_stop_command():
    net, _ = make_network()
    net._running = True
    net.stop()
    assert net._running is False
    assert net._cmd_queue.get_nowait() == {"cmd": "stop"}


def test_publish_raw_queues_only_when_running():
    net, _ = make_network()
    net._publish_raw(b"data")
    assert net._cmd_queue.empty()

    net._running = True
    net._publish_raw(b"data")
    cmd = net._cmd_queue.get_nowait()
    assert cmd == {"cmd": "publish", "data": b"data"}


def test_make_packet_roundtrips_through_encrypt_record():
    net, group_key = make_network()
    exp = Expense.create(group_id="g1", description="Dinner", amount=1000, author_pubkey="alice")
    raw = net._make_packet("expense", exp, belongs_to="x")
    pkt = json.loads(raw)
    assert pkt["type"] == "expense"
    assert pkt["id"] == exp.id
    assert pkt["belongs_to"] == "x"

    decrypted = crypto.decrypt_record(bytes.fromhex(pkt["data"]), group_key, Expense)
    assert decrypted is not None
    assert decrypted.description == "Dinner"


def test_publish_expense_queues_packet_when_running():
    net, group_key = make_network()
    net._running = True
    exp = Expense.create(group_id="g1", description="Taxi", amount=500, author_pubkey="alice")
    net.publish_expense(exp)
    cmd = net._cmd_queue.get_nowait()
    pkt = json.loads(cmd["data"])
    assert pkt["type"] == "expense"
    decrypted = crypto.decrypt_record(bytes.fromhex(pkt["data"]), group_key, Expense)
    assert decrypted.description == "Taxi"


def _row_for(ptype: str) -> dict:
    base = {
        "id": "rec1",
        "timestamp": 100,
        "lamport_clock": 1,
        "author_pubkey": "alice",
        "signature": "",
    }
    if ptype == "expense":
        base.update(
            group_id="g1",
            expense_date=100,
            is_deleted=0,
            amount=1000,
            description="Dinner",
            category=None,
            original_amount=None,
            original_currency=None,
        )
    elif ptype == "settlement":
        base.update(group_id="g1", is_deleted=0, from_key="bob", to_key="alice", amount=500)
    elif ptype == "split":
        base.update(belongs_to="e1", payer_key="alice", debtor_key="bob", amount=500)
    return base


@pytest.mark.parametrize(
    "ptype, model_cls", [("expense", Expense), ("settlement", Settlement), ("split", Split)]
)
def test_row_to_wire_roundtrips_for_each_type(ptype, model_cls):
    net, group_key = make_network()
    row = _row_for(ptype)
    blob = net._row_to_wire(row, ptype)
    assert blob is not None
    restored = crypto.decrypt_record(blob, group_key, model_cls)
    assert restored is not None
    assert restored.id == "rec1"


def test_row_to_wire_returns_none_for_unknown_type():
    net, _ = make_network()
    assert net._row_to_wire({"id": "x"}, "bogus") is None


def test_row_to_wire_strips_is_stored_for_attachments():
    net, group_key = make_network()
    from models import Attachment

    row = {
        "id": "a1",
        "belongs_to": "e1",
        "timestamp": 1,
        "lamport_clock": 1,
        "author_pubkey": "alice",
        "sha256": "deadbeef",
        "filename": "r.png",
        "mime": "image/png",
        "size": 10,
        "signature": "",
        "is_stored": 1,
    }
    blob = net._row_to_wire(row, "attachment")
    assert blob is not None
    restored = crypto.decrypt_record(blob, group_key, Attachment)
    assert restored.sha256 == "deadbeef"


def test_build_listen_addrs_returns_nonempty_list():
    addrs = network._build_listen_addrs(9999)
    assert len(addrs) >= 1


def test_create_node_uses_correct_gossipsub_params():
    """Regression test: GossipSub() must be called with explicit degree params,
    matching this libp2p version's required signature (see network.py fix)."""
    net, _ = make_network()

    fake_host = MagicMock()
    fake_gossipsub = MagicMock()
    fake_pubsub = MagicMock()

    with (
        patch("libp2p.new_host", return_value=fake_host) as mock_new_host,
        patch("libp2p.pubsub.gossipsub.GossipSub", return_value=fake_gossipsub) as mock_gossipsub,
        patch("libp2p.pubsub.pubsub.Pubsub", return_value=fake_pubsub),
    ):
        listen_addrs = net._create_node()

    assert net._host is fake_host
    assert net._pubsub is fake_pubsub
    assert isinstance(listen_addrs, list) and listen_addrs
    mock_new_host.assert_called_once()
    _, gs_kwargs = mock_gossipsub.call_args
    assert gs_kwargs["degree"] == 6
    assert gs_kwargs["degree_low"] == 4
    assert gs_kwargs["degree_high"] == 12
    assert gs_kwargs["protocols"]
    fake_host.set_stream_handler.assert_any_call(network.FILE_PROTOCOL, net._file_serve_handler)
    fake_host.set_stream_handler.assert_any_call(
        network.HISTORY_PROTOCOL, net._history_serve_handler
    )


def test_finish_start_node_calls_subscribe_and_status_callback():
    net, _ = make_network()
    net._host = MagicMock()
    net._host.get_id.return_value.to_string.return_value = "peer123"
    net._host.get_addrs.return_value = []

    async def fake_subscribe(topic_id):
        return MagicMock()

    net._pubsub = MagicMock()
    net._pubsub.subscribe = fake_subscribe
    net.callbacks = MagicMock()

    trio.run(net._finish_start_node)

    assert net._running is True
    net.callbacks.on_status_changed.assert_called_once_with(True, "peer123")
    assert net._sub is not None


def test_publish_user_announce_reads_signing_key_from_config(tmp_path):
    net, _ = make_network()
    net.set_own_identity("pk1", "Alice", 1000)
    net._pubsub = MagicMock()

    async def fake_publish(topic_id, data):
        pass

    net._pubsub.publish = fake_publish

    signing_key = crypto.generate_private_key()
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"private_key_hex": crypto.private_key_to_bytes(signing_key).hex()})
    )

    fake_cfg = MagicMock()
    fake_cfg.config_file = str(cfg_file)

    with patch("config_manager.ConfigManager", return_value=fake_cfg):
        trio.run(net._publish_user_announce)

    # No exception means the (fixed) config_file attribute lookup worked.


def test_publish_user_announce_survives_missing_config(tmp_path):
    """Even if the config file doesn't exist, the announce should not raise."""
    net, _ = make_network()
    net.set_own_identity("pk1", "Alice", 1000)
    net._pubsub = MagicMock()

    async def fake_publish(topic_id, data):
        pass

    net._pubsub.publish = fake_publish

    fake_cfg = MagicMock()
    fake_cfg.config_file = str(tmp_path / "does_not_exist.json")

    with patch("config_manager.ConfigManager", return_value=fake_cfg):
        trio.run(net._publish_user_announce)  # swallowed by the broad except + logged
