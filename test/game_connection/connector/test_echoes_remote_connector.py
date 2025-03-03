import re
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from randovania.dol_patching.assembler import BaseInstruction
from randovania.game_connection.connection_base import InventoryItem
from randovania.game_connection.connector.echoes_remote_connector import EchoesRemoteConnector
from randovania.game_connection.connector.prime_remote_connector import DolRemotePatch
from randovania.game_connection.executor.memory_operation import MemoryOperationException, MemoryOperation
from randovania.game_description.resources.pickup_entry import PickupEntry
from randovania.game_description.resources.pickup_index import PickupIndex
from randovania.games.game import RandovaniaGame
from randovania.games.prime2.patcher.echoes_dol_patches import EchoesDolVersion
from randovania.generator.item_pool import pickup_creator
from randovania.layout.base.major_item_state import MajorItemState


@pytest.fixture(name="version")
def echoes_version():
    from randovania.games.prime2.patcher import echoes_dol_versions
    return echoes_dol_versions.ALL_VERSIONS[0]


@pytest.fixture(name="connector")
def echoes_remote_connector(version: EchoesDolVersion):
    connector = EchoesRemoteConnector(version, AsyncMock())
    return connector


async def test_is_this_version(connector: EchoesRemoteConnector):
    # Setup
    build_info = b"!#$MetroidBuildInfo!#$Build v1.028 10/18/2004 10:44:32"
    connector.executor.perform_single_memory_operation.return_value = build_info

    # Run
    assert await connector.is_this_version()


@pytest.mark.parametrize(["message_original", "message_encoded", "previous_size"], [
    ("Magoo", b'\x00M\x00a\x00g\x00o\x00o\x00\x00', 0),
    ("Magoo2", b'\x00M\x00a\x00g\x00o\x00o\x002\x00\x00\x00\x00', 0),
    ("Magoo", b'\x00M\x00a\x00g\x00o\x00o\x00 \x00\x00\x00\x00', 10),
])
async def test_write_string_to_game_buffer(connector: EchoesRemoteConnector, version: EchoesDolVersion,
                                           message_original, message_encoded, previous_size):
    # Setup
    connector._last_message_size = previous_size

    # Run
    result = connector._write_string_to_game_buffer(message_original)

    # Assert
    assert result == MemoryOperation(version.string_display.message_receiver_string_ref,
                                     write_bytes=message_encoded)


async def test_get_inventory_valid(connector: EchoesRemoteConnector):
    # Setup
    connector.executor.perform_memory_operations.side_effect = lambda ops: {
        op: struct.pack(">II", item.max_capacity, item.max_capacity)
        for op, item in zip(ops, connector.game.resource_database.item)
    }

    # Run
    inventory = await connector.get_inventory()

    # Assert
    assert inventory == {
        item: InventoryItem(item.max_capacity, item.max_capacity)
        for item in connector.game.resource_database.item
    }


async def test_get_inventory_invalid_capacity(connector: EchoesRemoteConnector):
    # Setup
    custom_inventory = {"Darkburst": InventoryItem(0, 50)}

    connector.executor.perform_memory_operations.side_effect = lambda ops: {
        op: struct.pack(">II",
                        *custom_inventory.get(item.short_name, InventoryItem(item.max_capacity, item.max_capacity)))
        for op, item in zip(ops, connector.game.resource_database.item)
    }

    # Run
    msg = "Received InventoryItem(amount=0, capacity=50) for Darkburst, which is an invalid state."
    with pytest.raises(MemoryOperationException, match=re.escape(msg)):
        await connector.get_inventory()


async def test_get_inventory_invalid_amount(connector: EchoesRemoteConnector):
    # Setup
    custom_inventory = {"Darkburst": InventoryItem(1, 0)}

    connector.executor.perform_memory_operations.side_effect = lambda ops: {
        op: struct.pack(">II",
                        *custom_inventory.get(item.short_name, InventoryItem(item.max_capacity, item.max_capacity)))
        for op, item in zip(ops, connector.game.resource_database.item)
    }

    # Run
    msg = "Received InventoryItem(amount=1, capacity=0) for Darkburst, which is an invalid state."
    with pytest.raises(MemoryOperationException, match=re.escape(msg)):
        await connector.get_inventory()


@pytest.mark.parametrize("capacity", [0, 10])
async def test_known_collected_locations_nothing(connector: EchoesRemoteConnector, capacity: int):
    # Setup
    connector.executor.perform_single_memory_operation.return_value = struct.pack(">II", 0, capacity)
    connector.execute_remote_patches = AsyncMock()

    # Run
    locations = await connector.known_collected_locations()

    # Assert
    assert locations == set()
    connector.execute_remote_patches.assert_not_awaited()


@pytest.mark.parametrize("capacity", [0, 10])
async def test_known_collected_locations_location(connector: EchoesRemoteConnector, version: EchoesDolVersion,
                                                  mocker, capacity):
    # Setup
    mock_item_patch: MagicMock = mocker.patch(
        "randovania.patching.prime.all_prime_dol_patches.adjust_item_amount_and_capacity_patch")

    connector.executor.perform_single_memory_operation.return_value = struct.pack(">II", 10, 10 + capacity)
    connector.execute_remote_patches = AsyncMock()

    # Run
    locations = await connector.known_collected_locations()

    # Assert
    mock_item_patch.assert_called_once_with(version.powerup_functions,
                                            RandovaniaGame.METROID_PRIME_ECHOES,
                                            connector.game.resource_database.multiworld_magic_item.extra["item_id"],
                                            -10)

    assert locations == {PickupIndex(9)}
    connector.execute_remote_patches.assert_awaited_once_with([DolRemotePatch([], mock_item_patch.return_value)])


async def test_receive_remote_pickups_nothing(connector: EchoesRemoteConnector):
    # Setup
    inventory = {connector.game.resource_database.multiworld_magic_item: InventoryItem(0, 0)}
    connector.execute_remote_patches = AsyncMock()

    # Run
    await connector.receive_remote_pickups(inventory, [])
    connector.execute_remote_patches.assert_not_awaited()


async def test_receive_remote_pickups_pending_location(connector: EchoesRemoteConnector):
    # Setup
    inventory = {connector.game.resource_database.multiworld_magic_item: InventoryItem(5, 15)}
    connector.execute_remote_patches = AsyncMock()

    # Run
    await connector.receive_remote_pickups(inventory, [])
    connector.execute_remote_patches.assert_not_awaited()


@pytest.mark.parametrize("in_cooldown", [False, True])
async def test_receive_remote_pickups_give_pickup(connector: EchoesRemoteConnector, version: EchoesDolVersion,
                                                       mocker, in_cooldown):
    # Setup
    mock_item_patch: MagicMock = mocker.patch(
        "randovania.patching.prime.all_prime_dol_patches.increment_item_capacity_patch")
    mock_call_display_hud_patch: MagicMock = mocker.patch(
        "randovania.patching.prime.all_prime_dol_patches.call_display_hud_patch")
    if in_cooldown:
        connector.message_cooldown = 1.0
    connector.execute_remote_patches = AsyncMock()

    pickup_patches = MagicMock()
    connector._write_string_to_game_buffer = MagicMock()
    connector._patches_for_pickup = AsyncMock(return_value=([pickup_patches, pickup_patches], "The Message"))

    inventory = {connector.game.resource_database.multiworld_magic_item: InventoryItem(0, 0)}
    permanent_pickups = [
        ("A", MagicMock()),
        ("B", MagicMock()),
    ]

    # Run
    await connector.receive_remote_pickups(inventory, permanent_pickups)

    # Assert
    if in_cooldown:
        connector.execute_remote_patches.assert_not_awaited()
        mock_item_patch.assert_not_called()
        connector._patches_for_pickup.assert_not_called()
        connector._write_string_to_game_buffer.assert_not_called()
        mock_call_display_hud_patch.assert_not_called()
        return

    mock_item_patch.assert_called_once_with(version.powerup_functions,
                                            RandovaniaGame.METROID_PRIME_ECHOES,
                                            connector.game.resource_database.multiworld_magic_item.extra["item_id"])
    connector._patches_for_pickup.assert_awaited_once_with(permanent_pickups[0][0], permanent_pickups[0][1], inventory)
    connector.execute_remote_patches.assert_awaited_once_with([
        DolRemotePatch([], pickup_patches),
        DolRemotePatch([], pickup_patches),
        DolRemotePatch([], mock_item_patch.return_value),
        DolRemotePatch(
            [connector._write_string_to_game_buffer.return_value],
            mock_call_display_hud_patch.return_value,
        ),
    ])
    connector._write_string_to_game_buffer.assert_called_once_with("The Message")
    mock_call_display_hud_patch.assert_called_once_with(version.string_display)


@pytest.mark.parametrize("has_item_percentage", [False, True])
async def test_patches_for_pickup(connector: EchoesRemoteConnector, version: EchoesDolVersion, mocker,
                                  generic_item_category, has_item_percentage, default_generator_params):
    # Setup
    mock_item_patch: MagicMock = mocker.patch(
        "randovania.patching.prime.all_prime_dol_patches.adjust_item_amount_and_capacity_patch")

    db = connector.game.resource_database

    item_percentage_resource = []
    if has_item_percentage:
        item_percentage_resource = [
            (db.item_percentage, 1),
        ]

    pickup = PickupEntry("Pickup", 0, generic_item_category, generic_item_category, progression=tuple(),
                         generator_params=default_generator_params,
                         extra_resources=(
                             (db.energy_tank, db.energy_tank.max_capacity),
                             *item_percentage_resource,
                         ))
    inventory = {
        db.multiworld_magic_item: InventoryItem(0, 0),
        db.energy_tank: InventoryItem(1, 1),
    }

    # Run
    patches, message = await connector._patches_for_pickup("Someone", pickup, inventory)

    # Assert
    mock_item_patch.assert_called_once_with(version.powerup_functions,
                                            RandovaniaGame.METROID_PRIME_ECHOES,
                                            db.energy_tank.extra["item_id"],
                                            db.energy_tank.max_capacity)
    assert patches == [mock_item_patch.return_value]
    assert message == "Received Pickup from Someone."


async def test_execute_remote_patches(connector: EchoesRemoteConnector, version: EchoesDolVersion, mocker):
    # Setup
    patch_address, patch_bytes = MagicMock(), MagicMock()
    mock_remote_execute: MagicMock = mocker.patch(
        "randovania.patching.prime.all_prime_dol_patches.create_remote_execution_body",
        return_value=(patch_address, patch_bytes)
    )

    memory_op_a = MemoryOperation(1234, write_bytes=b"1234")
    instructions = [BaseInstruction(), BaseInstruction()]
    patches = [
        DolRemotePatch([memory_op_a], instructions[:1]),
        DolRemotePatch([], instructions[1:]),
    ]
    memory_operations = [
        memory_op_a,
        MemoryOperation(patch_address, write_bytes=patch_bytes),
        MemoryOperation(version.cstate_manager_global + 0x2, write_bytes=b"\x01"),
    ]

    # Run
    await connector.execute_remote_patches(patches)

    # Assert
    mock_remote_execute.assert_called_once_with(RandovaniaGame.METROID_PRIME_ECHOES, version.string_display, instructions)
    connector.executor.perform_memory_operations.assert_awaited_once_with(memory_operations)


@pytest.mark.parametrize("correct_vtable", [False, True])
@pytest.mark.parametrize("has_pending_op", [False, True])
@pytest.mark.parametrize("has_world", [False, True])
async def test_fetch_game_status(connector: EchoesRemoteConnector, version: EchoesDolVersion,
                                 has_world, has_pending_op, correct_vtable):
    # Setup
    expected_world = connector.game.world_list.worlds[0]

    connector.executor.perform_memory_operations.side_effect = lambda ops: {
        ops[0]: expected_world.extra["asset_id"].to_bytes(4, "big") if has_world else b"DEAD",
        ops[1]: b"\x01" if has_pending_op else b"\x00",
        ops[2]: version.cplayer_vtable.to_bytes(4, "big") if correct_vtable else b"CAFE",
    }

    # Run
    actual_has_op, actual_world = await connector.current_game_status()

    # Assert
    if has_world and correct_vtable:
        assert actual_world is expected_world
    else:
        assert actual_world is None
    assert actual_has_op == has_pending_op


async def test_receive_required_missile_launcher(connector: EchoesRemoteConnector,
                                                 echoes_item_database, echoes_resource_database):
    pickup = pickup_creator.create_major_item(
        echoes_item_database.major_items["Missile Launcher"],
        MajorItemState(included_ammo=(5,)),
        True,
        echoes_resource_database,
        echoes_item_database.ammo["Missile Expansion"],
        True,
    )

    connector.execute_remote_patches = AsyncMock()
    permanent_pickups = (("Received Missile Launcher from Someone Else", pickup),)

    inventory = {
        echoes_resource_database.multiworld_magic_item: InventoryItem(0, 0),
    }

    # Run
    await connector.receive_remote_pickups(
        inventory, permanent_pickups
    )

    connector.execute_remote_patches.assert_awaited_once()
    assert len(connector.execute_remote_patches.call_args[0][0]) == 5

