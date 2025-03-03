import dataclasses
import json
from unittest.mock import PropertyMock, MagicMock

import pytest

from randovania.exporter import pickup_exporter
from randovania.game_description import default_database
from randovania.game_description.assignment import PickupTarget
from randovania.game_description.resources.pickup_index import PickupIndex
from randovania.game_description.world.node import GenericNode, NodeLocation
from randovania.game_description.world.node_identifier import NodeIdentifier
from randovania.games.dread.exporter.patch_data_factory import DreadPatchDataFactory, DreadAcquiredMemo, \
    get_resources_for_details
from randovania.games.dread.layout.dread_cosmetic_patches import DreadCosmeticPatches
from randovania.games.game import RandovaniaGame
from randovania.generator.item_pool import pickup_creator
from randovania.interface_common.players_configuration import PlayersConfiguration
from randovania.layout.base.ammo_state import AmmoState
from randovania.layout.base.major_item_state import MajorItemState
from randovania.layout.base.pickup_model import PickupModelStyle
from randovania.layout.layout_description import LayoutDescription
from randovania.layout.preset import Preset


def test_create_patch_data(test_files_dir, mocker):
    # Setup
    file = test_files_dir.joinpath("log_files", "dread_1.rdvgame")
    description = LayoutDescription.from_file(file)
    players_config = PlayersConfiguration(0, {0: "Dread"})
    cosmetic_patches = DreadCosmeticPatches()
    mocker.patch("randovania.layout.layout_description.LayoutDescription.shareable_word_hash",
                 new_callable=PropertyMock, return_value="Words Hash")
    mocker.patch("randovania.layout.layout_description.LayoutDescription.shareable_hash",
                 new_callable=PropertyMock, return_value="$$$$$")

    # Run
    data = DreadPatchDataFactory(description, players_config, cosmetic_patches).create_data()

    # Expected Result
    with test_files_dir.joinpath("dread_expected_data.json").open("r") as file:
        expected_data = json.load(file)

    assert data == expected_data


def _preset_with_locked_pb(preset: Preset, locked: bool):
    item_database = default_database.item_database_for_game(RandovaniaGame.METROID_DREAD)
    preset = dataclasses.replace(
        preset,
        configuration=dataclasses.replace(
            preset.configuration,
            ammo_configuration=preset.configuration.ammo_configuration.replace_state_for_ammo(
                item_database.ammo["Power Bomb Tank"],
                AmmoState(requires_major_item=locked),
            )
        )
    )
    return preset


@pytest.mark.parametrize("locked", [False, True])
def test_pickup_data_for_pb_expansion(locked, dread_game_description, preset_manager):
    item_database = default_database.item_database_for_game(RandovaniaGame.METROID_DREAD)
    resource_db = dread_game_description.resource_database

    # Setup
    pickup = pickup_creator.create_ammo_expansion(
        item_database.ammo["Power Bomb Tank"],
        [2],
        locked,
        resource_db,
    )

    creator = pickup_exporter.PickupExporterSolo(DreadAcquiredMemo.with_expansion_text())

    # Run
    details = creator.export(PickupIndex(0), PickupTarget(pickup, 0), pickup, PickupModelStyle.ALL_VISIBLE)
    result = get_resources_for_details(details)

    # Assert
    assert result ==[
        {
            "item_id": "ITEM_WEAPON_POWER_BOMB_MAX" if locked else "ITEM_WEAPON_POWER_BOMB",
            "quantity": 2
        }
    ]


@pytest.mark.parametrize("locked", [False, True])
def test_pickup_data_for_main_pb(locked, dread_game_description, preset_manager):
    item_database = default_database.item_database_for_game(RandovaniaGame.METROID_DREAD)
    resource_db = dread_game_description.resource_database

    # Setup
    pickup = pickup_creator.create_major_item(
        item_database.major_items["Power Bomb"],
        MajorItemState(included_ammo=(3,)),
        include_percentage=False,
        resource_database=resource_db,
        ammo=item_database.ammo["Power Bomb Tank"],
        ammo_requires_major_item=locked,
    )

    creator = pickup_exporter.PickupExporterSolo(DreadAcquiredMemo.with_expansion_text())

    # Run
    details = creator.export(PickupIndex(0), PickupTarget(pickup, 0), pickup, PickupModelStyle.ALL_VISIBLE)
    result = get_resources_for_details(details)

    # Assert
    assert result == [
        {
            "item_id": "ITEM_WEAPON_POWER_BOMB",
            "quantity": 3
        }
    ]


def test_pickup_data_for_a_major(dread_game_description, preset_manager):
    item_database = default_database.item_database_for_game(RandovaniaGame.METROID_DREAD)
    resource_db = dread_game_description.resource_database

    preset = preset_manager.default_preset_for_game(RandovaniaGame.METROID_DREAD).get_preset()
    description = MagicMock(spec=LayoutDescription)
    description.all_patches = {0: MagicMock()}
    description.get_preset.return_value = preset
    description.get_seed_for_player.return_value = 1000

    # Setup
    pickup = pickup_creator.create_major_item(
        item_database.major_items["Speed Booster"],
        MajorItemState(),
        include_percentage=False,
        resource_database=resource_db,
        ammo=None,
        ammo_requires_major_item=False,
    )

    factory = DreadPatchDataFactory(description, PlayersConfiguration(0, {0: "Dread"}), MagicMock())
    creator = pickup_exporter.PickupExporterSolo(DreadAcquiredMemo.with_expansion_text())

    # Run
    details = creator.export(PickupIndex(0), PickupTarget(pickup, 0), pickup, PickupModelStyle.ALL_VISIBLE)
    result = factory._pickup_detail_for_target(details)

    # Assert
    assert result == {
        "pickup_type": "actor",
        "caption": "Speed Booster acquired.",
        "resources": [
            {
                "item_id": "ITEM_SPEED_BOOSTER",
                "quantity": 1
            }
        ],
        "pickup_actor": {
            "scenario": "s010_cave",
            "layer": "default",
            "actor": "ItemSphere_ChargeBeam"
        },
        "model": [
            "powerup_speedbooster"
        ],
        "map_icon": {
            "icon_id": "powerup_speedbooster",
            'original_actor': {'actor': 'powerup_chargebeam',
                               'layer': 'default',
                               'scenario': 's010_cave'}
        }
    }

@pytest.fixture
def setup_and_teardown_for_wrong_custom_spawn():
    # modify the default start to have no collision_camera (asset_id) and no vanilla
    # actor name for a start point
    game_desc = default_database.game_description_for(RandovaniaGame.METROID_DREAD)
    world = game_desc.world_list.world_with_name("Artaria")
    area = world.area_by_name("Intro Room")
    node = area.node_with_name("Start Point")
    modified_node = dataclasses.replace(node, extra={})
    area.nodes.remove(node)
    area.nodes.append(modified_node)
    asset_id = area.extra["asset_id"]
    del area.extra["asset_id"]
    yield
    area.nodes.remove(modified_node)
    area.nodes.append(node)
    area.extra["asset_id"] = asset_id

def test_create_patch_with_wrong_custom_spawn(test_files_dir, mocker, setup_and_teardown_for_wrong_custom_spawn):
    # test for a not createable spawn point
    file = test_files_dir.joinpath("log_files", "dread_1.rdvgame")
    description = LayoutDescription.from_file(file)
    players_config = PlayersConfiguration(0, {0: "Dread"})
    cosmetic_patches = DreadCosmeticPatches()
    mocker.patch("randovania.layout.layout_description.LayoutDescription.shareable_word_hash",
                 new_callable=PropertyMock, return_value="Words Hash")
    mocker.patch("randovania.layout.layout_description.LayoutDescription.shareable_hash",
                 new_callable=PropertyMock, return_value="$$$$$")

    patcher = DreadPatchDataFactory(description, players_config, cosmetic_patches)
    with pytest.raises(KeyError, match="Artaria/Intro Room/Start Point has neither a start_point_actor_name nor the area has a collision_camera_name for a custom start point"):
        patcher.create_data()

@pytest.fixture
def setup_and_teardown_for_custom_spawn():
    # modify a node to be a valid start point without a vanilla spawn
    game_desc = default_database.game_description_for(RandovaniaGame.METROID_DREAD)
    world = game_desc.world_list.world_with_name("Artaria")
    area = world.area_by_name("Charge Tutorial")
    node = area.node_with_name("Start Point")
    modified_node = dataclasses.replace(node, valid_starting_location=True)
    area.nodes.remove(node)
    area.nodes.append(modified_node)
    yield
    area.nodes.remove(modified_node)
    area.nodes.append(node)


def test_create_patch_with_custom_spawn(test_files_dir, mocker, setup_and_teardown_for_custom_spawn):
    # test for custom spawn point referenced by starting location and teleporters
    file = test_files_dir.joinpath("log_files", "dread_2.rdvgame")
    description = LayoutDescription.from_file(file)
    players_config = PlayersConfiguration(0, {0: "Dread"})
    cosmetic_patches = DreadCosmeticPatches()
    mocker.patch("randovania.layout.layout_description.LayoutDescription.shareable_word_hash",
                 new_callable=PropertyMock, return_value="Words Hash")
    mocker.patch("randovania.layout.layout_description.LayoutDescription.shareable_hash",
                 new_callable=PropertyMock, return_value="$$$$$")
  
    data = DreadPatchDataFactory(description, players_config, cosmetic_patches).create_data()
    # only one spawn point should be created
    expected_new_spawn = [{'new_actor': {'actor': 'SP_RDV_000', 'scenario': 's010_cave'},
                            'location': {'x': 6492.78, 'y': -9500.0, 'z': 0.0},
                            'collision_camera_name': 'collision_camera_001'}]
    expected_start = {'scenario': 's010_cave', 'actor': 'SP_RDV_000'}
    assert data["new_spawn_points"] == expected_new_spawn
    assert data["starting_location"] == expected_start
