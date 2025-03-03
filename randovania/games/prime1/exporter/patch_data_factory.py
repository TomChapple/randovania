from random import Random

import randovania
from randovania.exporter import pickup_exporter, item_names
from randovania.exporter.hints import guaranteed_item_hint, credits_spoiler
from randovania.exporter.patch_data_factory import BasePatchDataFactory
from randovania.game_description.assignment import PickupTarget
from randovania.game_description.resources.item_resource_info import ItemResourceInfo
from randovania.game_description.resources.resource_database import ResourceDatabase
from randovania.game_description.resources.resource_info import ResourceCollection
from randovania.game_description.world.area_identifier import AreaIdentifier
from randovania.game_description.world.dock_node import DockNode
from randovania.game_description.world.node_identifier import NodeIdentifier
from randovania.game_description.world.pickup_node import PickupNode
from randovania.game_description.world.teleporter_node import TeleporterNode
from randovania.game_description.world.world_list import WorldList, World
from randovania.games.game import RandovaniaGame
from randovania.games.prime1.exporter.hint_namer import PrimeHintNamer
from randovania.games.prime1.exporter.vanilla_maze_seeds import VANILLA_MAZE_SEEDS
from randovania.games.prime1.layout.hint_configuration import ArtifactHintMode, PhazonSuitHintMode
from randovania.games.prime1.layout.prime_configuration import PrimeConfiguration, RoomRandoMode, LayoutCutsceneMode
from randovania.games.prime1.layout.prime_cosmetic_patches import PrimeCosmeticPatches
from randovania.games.prime1.patcher import prime1_elevators, prime_items
from randovania.generator.item_pool import pickup_creator
from randovania.layout.layout_description import LayoutDescription

_EASTER_EGG_SHINY_MISSILE = 1024

_STARTING_ITEM_NAME_TO_INDEX = {
    "powerBeam": "Power",
    "ice": "Ice",
    "wave": "Wave",
    "plasma": "Plasma",
    "missiles": "Missile",
    "scanVisor": "Scan",
    "bombs": "Bombs",
    "powerBombs": "PowerBomb",
    "flamethrower": "Flamethrower",
    "thermalVisor": "Thermal",
    "charge": "Charge",
    "superMissile": "Supers",
    "grapple": "Grapple",
    "xray": "X-Ray",
    "iceSpreader": "IceSpreader",
    "spaceJump": "SpaceJump",
    "morphBall": "MorphBall",
    "combatVisor": "Combat",
    "boostBall": "Boost",
    "spiderBall": "Spider",
    "gravitySuit": "GravitySuit",
    "variaSuit": "VariaSuit",
    "phazonSuit": "PhazonSuit",
    "energyTanks": "EnergyTank",
    "wavebuster": "Wavebuster"
}

_MODEL_MAPPING = {
    (RandovaniaGame.METROID_PRIME_ECHOES, "CombatVisor INCOMPLETE"): "Combat Visor",
    (RandovaniaGame.METROID_PRIME_ECHOES, "ChargeBeam INCOMPLETE"): "Charge Beam",
    (RandovaniaGame.METROID_PRIME_ECHOES, "SuperMissile"): "Super Missile",
    (RandovaniaGame.METROID_PRIME_ECHOES, "ScanVisor INCOMPLETE"): "Scan Visor",
    (RandovaniaGame.METROID_PRIME_ECHOES, "VariaSuit INCOMPLETE"): "Varia Suit",
    (RandovaniaGame.METROID_PRIME_ECHOES, "DarkSuit"): "Varia Suit",
    (RandovaniaGame.METROID_PRIME_ECHOES, "LightSuit"): "Varia Suit",
    (RandovaniaGame.METROID_PRIME_ECHOES, "MorphBall INCOMPLETE"): "Morph Ball",
    (RandovaniaGame.METROID_PRIME_ECHOES, "MorphBallBomb"): "Morph Ball Bomb",
    (RandovaniaGame.METROID_PRIME_ECHOES, "BoostBall"): "Boost Ball",
    (RandovaniaGame.METROID_PRIME_ECHOES, "SpiderBall"): "Spider Ball",
    (RandovaniaGame.METROID_PRIME_ECHOES, "PowerBomb"): "Power Bomb",
    (RandovaniaGame.METROID_PRIME_ECHOES, "PowerBombExpansion"): "Power Bomb Expansion",
    (RandovaniaGame.METROID_PRIME_ECHOES, "MissileExpansion"): "Missile",
    (RandovaniaGame.METROID_PRIME_ECHOES, "MissileExpansionPrime1"): "Missile",
    (RandovaniaGame.METROID_PRIME_ECHOES, "MissileLauncher"): "Missile",
    (RandovaniaGame.METROID_PRIME_ECHOES, "GrappleBeam"): "Grapple Beam",
    (RandovaniaGame.METROID_PRIME_ECHOES, "SpaceJumpBoots"): "Space Jump Boots",
    (RandovaniaGame.METROID_PRIME_ECHOES, "EnergyTank"): "Energy Tank",
}

# The following locations have cutscenes that weren't removed
_LOCATIONS_WITH_MODAL_ALERT = {
    63,  # Artifact Temple
    23,  # Watery Hall (Charge Beam)
    50,  # Research Core
}

# Show a popup on collection if two or more is for another player.
# The location to the right is considered for the count, but it can't show a popup.
_LOCATIONS_GROUPED_TOGETHER = [
    ({0, 1, 2, 3}, None),  # Main Plaza
    ({5, 6, 7}, None),  # Ruined Shrine (all 3)
    ({94}, 97),  # Warrior shrine -> Fiery Shores Tunnel
    ({55}, 54),  # Gravity Chamber: Upper -> Lower
    ({19, 17}, None),  # Hive Totem + Transport Access North
    ({59}, 58),  # Alcove -> Landing Site
    ({62, 65}, None),  # Root Cave + Arbor Chamber
    ({15, 16}, None),  # Ruined Gallery
    ({52, 53}, None),  # Research Lab Aether
]


def _remove_empty(d):
    """recursively remove empty lists, empty dicts, or None elements from a dictionary"""

    def empty(x):
        return x is None or x == {} or x == []

    if not isinstance(d, (dict, list)):
        return d
    elif isinstance(d, list):
        return [v for v in (_remove_empty(v) for v in d) if not empty(v)]
    else:
        return {k: v for k, v in ((k, _remove_empty(v)) for k, v in d.items()) if not empty(v)}


def prime1_pickup_details_to_patcher(detail: pickup_exporter.ExportedPickupDetails,
                                     modal_hud_override: bool,
                                     pickup_markers: bool,
                                     rng: Random) -> dict:
    model = detail.model.as_json

    name = detail.name
    collection_text = detail.collection_text[0]
    pickup_type = "Nothing"
    count = 0

    for resource, quantity in detail.conditional_resources[0].resources:
        if resource.extra["item_id"] >= 1000:
            continue
        pickup_type = resource.long_name
        count = quantity
        break

    if (model["name"] == "Missile" and not detail.other_player
            and "Missile Expansion" in collection_text
            and rng.randint(0, _EASTER_EGG_SHINY_MISSILE) == 0):
        model["name"] = "Shiny Missile"
        collection_text = collection_text.replace("Missile Expansion", "Shiny Missile Expansion")
        name = name.replace("Missile Expansion", "Shiny Missile Expansion")

    result = {
        "type": pickup_type,
        "model": model,
        "scanText": f"{name}. {detail.description}".strip(),
        "hudmemoText": collection_text,
        "currIncrease": count,
        "maxIncrease": count,
        "respawn": False,
        "showIcon": pickup_markers
    }
    if modal_hud_override:
        result["modalHudmemo"] = True

    return result


def _create_locations_with_modal_hud_memo(pickups: list[pickup_exporter.ExportedPickupDetails]) -> set[int]:
    result = set()

    for index in _LOCATIONS_WITH_MODAL_ALERT:
        if pickups[index].other_player:
            result.add(index)

    for indices, extra in _LOCATIONS_GROUPED_TOGETHER:
        num_other = sum(pickups[i].other_player for i in indices)
        if extra is not None:
            num_other += pickups[extra].other_player

        if num_other > 1:
            for index in indices:
                if pickups[index].other_player:
                    result.add(index)

    return result


def _starting_items_value_for(resource_database: ResourceDatabase,
                              starting_items: ResourceCollection, index: str) -> bool | int:
    item = resource_database.get_item(index)
    value = starting_items[item]
    if item.max_capacity > 1:
        return value
    else:
        return value > 0


def _name_for_location(world_list: WorldList, location: AreaIdentifier) -> str:
    loc = location.as_tuple
    if loc in prime1_elevators.RANDOMPRIME_CUSTOM_NAMES and loc != ("Frigate Orpheon", "Exterior Docking Hangar"):
        return prime1_elevators.RANDOMPRIME_CUSTOM_NAMES[loc]
    else:
        return world_list.area_name(world_list.area_by_area_location(location), separator=":")


def _name_for_start_location(world_list: WorldList, location: NodeIdentifier) -> str:
    # small helper function as long as teleporter nodes use AreaIdentifier and starting locations use NodeIdentifier
    area_loc = location.area_identifier
    return _name_for_location(world_list, area_loc)


def _create_results_screen_text(description: LayoutDescription) -> str:
    return "{} | Seed Hash - {} ({})".format(
        randovania.VERSION, description.shareable_word_hash, description.shareable_hash)

def _random_factor(rng: Random, min: float, max: float, target: float):
    # return a random float between (min, max) biased towards target (up to 1 re-roll to get closer)
    a = rng.uniform(min, max)
    b = rng.uniform(min, max)
    a_diff = abs(a - target)
    b_diff = abs(b - target)
    if a_diff > b_diff:
        return a
    return b

def _pick_random_point_in_aabb(rng: Random, aabb: list, room_name: str):
    # return a quasi-random point within the provided aabb, but bias towards being closer to in-bounds
    offset_xy = 0.0
    offset_max_z = 0.0

    ROOMS_THAT_NEED_HELP = [
        "Landing Site",
        "Alcove",
        "Frigate Crash Site",
        "Sunchamber",
        "Triclops Pit",
        "Elite Quarters",
        "Quarantine Cave",
        "Burn Dome",
        "Research Lab Hydra",
        "Research Lab Aether",
    ]

    if room_name in ROOMS_THAT_NEED_HELP:
        offset_xy = 0.1
        offset_max_z = -0.3

    x_factor = _random_factor(rng, 0.15 + offset_xy, 0.85 - offset_xy, 0.5)
    y_factor = _random_factor(rng, 0.15 + offset_xy, 0.85 - offset_xy, 0.5)
    z_factor = _random_factor(rng, 0.1, 0.8 + offset_max_z, 0.35)

    return [
        aabb[0] + (aabb[3] - aabb[0]) * x_factor,
        aabb[1] + (aabb[4] - aabb[1]) * y_factor,
        aabb[2] + (aabb[5] - aabb[2]) * z_factor,
    ]

def _serialize_dock_modifications(world_data, worlds: list[World], room_rando_mode: RoomRandoMode, rng: Random):
    if room_rando_mode == RoomRandoMode.NONE:
        return

    for world in worlds:
        area_dock_nums = dict()
        attached_areas = dict()
        size_indices = dict()
        candidates = list()
        default_connections_node_name = dict()
        dock_num_by_area_node = dict()
        is_nonstandard = dict()
        disabled_doors = set()

        # collect dock info for all areas
        for area in world.areas:
            area_dock_nums[area.name] = list()
            attached_areas[area.name] = list()
            for node in area.nodes:
                if not isinstance(node, DockNode):
                    continue
                index = node.extra["dock_index"]
                dock_num_by_area_node[(area.name, node.name)] = index
                is_nonstandard[(area.name, index)] = node.extra["nonstandard"]
                default_connections_node_name[(area.name, index)] = (
                    node.default_connection.area_name, node.default_connection.node_name)

                if node.default_dock_weakness.name == "Permanently Locked":
                    disabled_doors.add((area.name, index))

                if node.extra["nonstandard"]:
                    continue
                area_dock_nums[area.name].append(index)
                attached_areas[area.name].append(node.default_connection.area_name)
                candidates.append((area.name, index))
            size_indices[area.name] = area.extra["size_index"]

        default_connections = dict()
        for (src_name, src_dock) in default_connections_node_name:
            (dst_name, dst_node_name) = default_connections_node_name[(src_name, src_dock)]

            try:
                dst_dock = dock_num_by_area_node[(dst_name, dst_node_name)]
            except KeyError:
                continue

            default_connections[(src_name, src_dock)] = (dst_name, dst_dock)

        for area_name, dock_num in candidates:
            room = world_data[world.name]["rooms"][area_name]
            if "doors" not in room:
                room["doors"] = dict()

            def helper(_dock_num):
                dock_num_key = str(_dock_num)

                if dock_num_key not in room["doors"]:
                    room["doors"][dock_num_key] = dict()

                if "destination" not in room["doors"][dock_num_key]:
                    room["doors"][dock_num_key]["destination"] = dict()

            helper(dock_num)

            for dock_num in area_dock_nums[area.name]:
                helper(dock_num)

        # Shuffle order which candidates are processed
        rng.shuffle(candidates)

        used_room_pairings = list()

        def are_rooms_compatible(src_name, src_dock, dst_name, dst_dock, mode: RoomRandoMode):
            if src_name is None or dst_name is None:
                # print("none name")
                return False

            # both rooms must have patchable docks
            if len(area_dock_nums[src_name]) == 0 or len(area_dock_nums[dst_name]) == 0:
                # print("unpatchable room(s)")
                return False

            # destinations cannot be in the same room
            if src_name == dst_name:
                # print("same room")
                return False

            # src/dst must not be exempt
            if src_dock is not None and is_nonstandard[(src_name, src_dock)]:
                # print("src exempt")
                return False
            if dst_dock is not None and is_nonstandard[(dst_name, dst_dock)]:
                # print("dst exempt")
                return False

            # rooms cannot be neighbors
            if src_name in attached_areas[dst_name]:
                if mode == RoomRandoMode.ONE_WAY:
                    # print("neighbor")
                    return False

                # Unless it's a vanilla 2-way connection
                if default_connections[(src_name, src_dock)] != (dst_name, dst_dock):
                    # print("two-way non-neighbor")
                    return False

            # rooms can only connect to another room up to once
            if {src_name, dst_name} in used_room_pairings:
                # Except for one-way in impact crater, this edge case works fine and is desireable
                if not (mode == RoomRandoMode.ONE_WAY and world.name == "Impact Crater"):
                    # print("double connection")
                    return False

            # The two rooms must not crash if drawn at the same time (size_index > 1.0)
            if size_indices[src_name] + size_indices[dst_name] >= 1.0:
                # print("too big")
                return False

            return True

        if room_rando_mode == RoomRandoMode.ONE_WAY:
            for area in world.areas:
                for dock_num in area_dock_nums[area.name]:
                    # First try each of the unused docks
                    dst_name = None
                    dst_dock = None
                    for (name, dock) in candidates:
                        if are_rooms_compatible(area.name, None, name, None, room_rando_mode):
                            dst_name = name
                            dst_dock = dock
                            break

                    # If that wasn't successful, pick random destinations until it works out
                    deadman_count = 1000
                    while dst_name is None or dst_dock is None or not are_rooms_compatible(area.name, dock_num,
                                                                                            dst_name, dst_dock,
                                                                                            room_rando_mode):

                        deadman_count -= 1
                        if deadman_count == 0:
                            raise Exception(
                                f"Failed to find suitible destination for {area.name}:{dock_num}")

                        dst_name = rng.choice(world.areas).name
                        dst_dock = None

                        if len(area_dock_nums[dst_name]) == 0:
                            continue

                        dst_dock = rng.choice(area_dock_nums[dst_name])

                    # Don't use this dock as a destination again unless there are no other options
                    try:
                        candidates.remove((dst_name, dst_dock))
                    except ValueError:
                        # print("re-used %s:%d" % (dst_name, dst_dock))
                        pass

                    used_room_pairings.append({area.name, dst_name})

                    d = world_data[world.name]["rooms"][area.name]["doors"][str(dock_num)]["destination"]
                    d["roomName"] = name
                    d["dockNum"] = dst_dock
 
        elif room_rando_mode == RoomRandoMode.TWO_WAY:
            # List containing:
            #   - set of len=2, each containing
            #       - tuple of len=2 for (room_name, dock)
            shuffled = list()

            def next_candidate(max_index):
                for (src_name, src_dock) in candidates:
                    if size_indices[src_name] > max_index:
                        return (src_name, src_dock)
                return (None, None)

            def pick_random_dst(src_name, src_dock):
                for (dst_name, dst_dock) in candidates:
                    if are_rooms_compatible(src_name, src_dock, dst_name, dst_dock,
                                            room_rando_mode):
                        return (dst_name, dst_dock)
                return (None, None)

            def remove_pair(shuffled_pair: set):
                shuffled.remove(shuffled_pair)

                shuffled_pair = sorted(list(shuffled_pair))
                assert len(shuffled_pair) == 2
                a = shuffled_pair[0]
                b = shuffled_pair[1]

                candidates.append(a)
                candidates.append(b)

                (a_name, a_dock) = a
                (b_name, b_dock) = b
                used_room_pairings.remove({a_name, b_name})

                world_data[world.name]["rooms"][a_name]["doors"][str(a_dock)]["destination"] = dict()
                world_data[world.name]["rooms"][b_name]["doors"][str(b_dock)]["destination"] = dict()

            # Randomly pick room sources, starting with the largest room first, then randomly
            # pick a compatible destination
            max_index = 1.01
            while len(candidates) != 0:
                assert len(candidates) % 2 == 0

                if max_index < -0.00001:
                    raise Exception("Failed to find pairings for %s" % str(candidates))

                (src_name, src_dock) = next_candidate(max_index)

                if src_name is None:
                    # lower the room size criteria and try again
                    max_index -= 0.01
                    continue

                (dst_name, dst_dock) = pick_random_dst(src_name, src_dock)
                if dst_name is None:
                    # This room have no valid destinations in the pool, randomly unpair two rooms and try again
                    remove_pair(rng.choice(shuffled))
                    continue

                assert {(src_name, src_dock), (dst_name, dst_dock)} not in shuffled

                candidates.remove((src_name, src_dock))
                candidates.remove((dst_name, dst_dock))
                shuffled.append({(src_name, src_dock), (dst_name, dst_dock)})
                used_room_pairings.append({src_name, dst_name})

                d = world_data[world.name]["rooms"][src_name]["doors"][str(src_dock)]["destination"]
                d["roomName"] = dst_name
                d["dockNum"] = dst_dock

                d = world_data[world.name]["rooms"][dst_name]["doors"][str(dst_dock)]["destination"]
                d["roomName"] = src_name
                d["dockNum"] = src_dock

                # print("%s:%d <--> %s:%d" % (src_name, src_dock, dst_name, dst_dock))

                # If we just finished placing all rooms, check if there are unconnected components
                # and if so, re-roll some rooms
                if len(candidates) == 0:
                    import networkx

                    # Model as networkx graph object
                    room_connections = list()
                    for room_name in world_data[world.name]["rooms"]:
                        room = world_data[world.name]["rooms"][room_name]
                        if "doors" not in room:
                            continue

                        for dock_num in room["doors"]:
                            if "destination" not in room["doors"][dock_num]:
                                continue

                            if len(room["doors"][dock_num]["destination"]) == 0:
                                continue

                            if (room_name, int(dock_num)) in disabled_doors:
                                continue

                            dst_room_name = room["doors"][dock_num]["destination"]["roomName"]

                            assert {room_name, dst_room_name} in used_room_pairings

                            room_connections.append((room_name, dst_room_name))

                    # Handle unrandomized connections
                    for (src_name, src_dock) in is_nonstandard:
                        if (src_name, src_dock) in disabled_doors:
                            continue

                        if is_nonstandard[(src_name, src_dock)]:
                            (dst_name, dst_dock) = default_connections[(src_name, src_dock)]
                            room_connections.append((src_name, dst_name))

                    # model this world's connections as a graph
                    graph = networkx.DiGraph()
                    graph.add_edges_from(room_connections)

                    if not networkx.is_strongly_connected(graph):
                        # Split graph into strongly connected components
                        strongly_connected_components = sorted(networkx.strongly_connected_components(graph),
                                                                key=len, reverse=True)
                        assert len(strongly_connected_components) > 1

                        def component_number(name):
                            i = 0
                            for component in strongly_connected_components:
                                if name in list(component):
                                    return i
                                i += 1

                        # randomly pick two room pairs which are not members of the same strongly connected
                        # component and # put back into pool for re-randomization (cross fingers that they
                        # connect the two strong components)
                        assert len(shuffled) > 2

                        # pick one randomly
                        rng.shuffle(shuffled)
                        a = shuffled[-1]
                        a = sorted(list(a))
                        (src_name_a, src_dock_a) = a[0]
                        (dst_name_a, dst_dock_a) = a[1]
                        a_component_num = component_number(src_name_a)

                        # pick a second which is not part of the same component
                        (src_name_b, src_dock_b, dst_name_b, dst_dock_b) = (None, None, None, None)
                        for b in shuffled:
                            b = sorted(list(b))
                            (src_name, src_dock) = b[0]
                            (dst_name, dst_dock) = b[1]
                            if component_number(src_name) == a_component_num:
                                continue
                            (src_name_b, src_dock_b, dst_name_b, dst_dock_b) = (
                                src_name, src_dock, dst_name, dst_dock)
                            break

                        # If we could not find two rooms that were part of two different components, still
                        # remove a random room pairing (this can happen if rooms exempt from randomization
                        # are causing fractured connectivity)
                        if src_name_b is None:
                            b = sorted(list(shuffled[0]))
                            (src_name_b, src_dock_b) = b[0]
                            (dst_name_b, dst_dock_b) = b[1]

                        # put back into pool
                        remove_pair({(src_name_a, src_dock_a), (dst_name_a, dst_dock_a)})
                        remove_pair({(src_name_b, src_dock_b), (dst_name_b, dst_dock_b)})

                        # do something different this time
                        rng.shuffle(candidates)


class PrimePatchDataFactory(BasePatchDataFactory):
    cosmetic_patches: PrimeCosmeticPatches
    configuration: PrimeConfiguration

    def game_enum(self) -> RandovaniaGame:
        return RandovaniaGame.METROID_PRIME

    def get_default_game_options(self):
        cosmetic_patches = self.cosmetic_patches
        return {
            "screenBrightness": cosmetic_patches.user_preferences.screen_brightness,
            "screenOffsetX": cosmetic_patches.user_preferences.screen_x_offset,
            "screenOffsetY": cosmetic_patches.user_preferences.screen_y_offset,
            "screenStretch": cosmetic_patches.user_preferences.screen_stretch,
            "soundMode": cosmetic_patches.user_preferences.sound_mode,
            "sfxVolume": cosmetic_patches.user_preferences.sfx_volume,
            "musicVolume": cosmetic_patches.user_preferences.music_volume,
            "visorOpacity": cosmetic_patches.user_preferences.hud_alpha,
            "helmetOpacity": cosmetic_patches.user_preferences.helmet_alpha,
            "hudLag": cosmetic_patches.user_preferences.hud_lag,
            "reverseYAxis": cosmetic_patches.user_preferences.invert_y_axis,
            "rumble": cosmetic_patches.user_preferences.rumble,
            "swapBeamControls": cosmetic_patches.user_preferences.swap_beam_controls,
        }

    def create_data(self) -> dict:
        # Setup
        db = self.game
        namer = PrimeHintNamer(self.description.all_patches, self.players_config)

        ammo_with_mains = [ammo.name for ammo, state in self.configuration.ammo_configuration.items_state.items()
                           if state.requires_major_item]
        if ammo_with_mains:
            raise ValueError("Preset has {} with required mains enabled. This is currently not supported.".format(
                " and ".join(ammo_with_mains)
            ))

        scan_visor = self.game.resource_database.get_item_by_name("Scan Visor")
        useless_target = PickupTarget(pickup_creator.create_nothing_pickup(db.resource_database),
                                      self.players_config.player_index)

        pickup_list = pickup_exporter.export_all_indices(
            self.patches,
            useless_target,
            db.world_list,
            self.rng,
            self.configuration.pickup_model_style,
            self.configuration.pickup_model_data_source,
            exporter=pickup_exporter.create_pickup_exporter(db, pickup_exporter.GenericAcquiredMemo(),
                                                            self.players_config),
            visual_etm=pickup_creator.create_visual_etm(),
        )
        modal_hud_override = _create_locations_with_modal_hud_memo(pickup_list)
        worlds = [world for world in db.world_list.worlds if world.name != "End of Game"]

        # Initialize serialized world data
        world_data = dict()
        for world in worlds:
            world_data[world.name] = {
                "transports": dict(),
                "rooms": dict(),
            }

            for area in world.areas:
                world_data[world.name]["rooms"][area.name] = {
                    "pickups": list(),
                    "doors": dict(),
                }
        
        # serialize elevator modifications
        for world in worlds:
            for area in world.areas:
                for node in area.nodes:
                    if not isinstance(node, TeleporterNode) or not node.editable:
                        continue

                    identifier = db.world_list.identifier_for_node(node)
                    target = _name_for_location(db.world_list, self.patches.get_elevator_connection_for(node))

                    source_name = prime1_elevators.RANDOMPRIME_CUSTOM_NAMES[(
                        identifier.area_location.world_name,
                        identifier.area_location.area_name,
                    )]
                    world_data[world.name]["transports"][source_name] = target

        # serialize pickup modifications
        for world in worlds:
            for area in world.areas:
                pickup_nodes = (node for node in area.nodes if isinstance(node, PickupNode))
                pickup_nodes = sorted(pickup_nodes, key=lambda n: n.pickup_index)
                for node in pickup_nodes:
                    pickup_index = node.pickup_index.index
                    pickup = prime1_pickup_details_to_patcher(pickup_list[pickup_index],
                                                              pickup_index in modal_hud_override,
                                                              self.cosmetic_patches.pickup_markers,
                                                              self.rng)

                    if node.extra.get("position_required"):
                        assert self.configuration.items_every_room
                        aabb = area.extra["aabb"]
                        pickup["position"] = _pick_random_point_in_aabb(self.rng, aabb, area.name)
                        pickup["jumboScan"] = True  # Scan this item through walls

                    world_data[world.name]["rooms"][area.name]["pickups"].append(pickup)

        # serialize room modifications
        if self.configuration.superheated_probability != 0:
            probability = self.configuration.superheated_probability / 1000.0
            for world in worlds:
                for area in world.areas:
                    world_data[world.name]["rooms"][area.name]["superheated"] = self.rng.random() < probability

        if self.configuration.submerged_probability != 0:
            probability = self.configuration.submerged_probability / 1000.0
            for world in worlds:
                for area in world.areas:
                    world_data[world.name]["rooms"][area.name]["submerge"] = self.rng.random() < probability

        # serialize door modifications
        for world in worlds:
            for area in world.areas:
                dock_nodes = (node for node in area.nodes if isinstance(node, DockNode))
                dock_nodes = sorted(dock_nodes, key=lambda n: n.extra["dock_index"])
                for node in dock_nodes:
                    node: DockNode = node
                    if node.extra.get("exclude_dock_rando", False):
                        continue

                    if self.patches.has_default_weakness(node):
                        continue

                    weakness = self.patches.get_dock_weakness_for(node)
                    dock_index = node.extra["dock_index"]
                    dock_data = {
                        "shieldType": weakness.extra["shieldType"],
                        "blastShieldType": weakness.extra.get("blastShieldType", "Empty")
                    }

                    world_data[world.name]["rooms"][area.name]["doors"][str(dock_index)] = dock_data

        # serialize dock destination modifications
        _serialize_dock_modifications(world_data, worlds, self.configuration.room_rando, self.rng)

        # serialize text modifications
        if self.configuration.hints.phazon_suit != PhazonSuitHintMode.DISABLED:
            try:
                phazon_suit_resource_info = self.game.resource_database.get_item_by_name("Phazon Suit")

                hint_texts: dict[ItemResourceInfo, str] = guaranteed_item_hint.create_guaranteed_hints_for_resources(
                    self.description.all_patches,
                    self.players_config,
                    namer,
                    self.configuration.hints.phazon_suit == PhazonSuitHintMode.HIDE_AREA,
                    [phazon_suit_resource_info],
                    True,
                )

                phazon_hint_text = hint_texts[phazon_suit_resource_info]

                if "Impact Crater" not in world_data:
                    world_data["Impact Crater"] = {
                        "transports": dict(),
                        "rooms": dict(),
                    }

                if "Crater Entry Point" not in world_data["Impact Crater"]["rooms"]:
                    world_data["Impact Crater"]["rooms"]["Crater Entry Point"] = {
                        "pickups": list(),
                        "doors": dict()
                    }

                world_data["Impact Crater"]["rooms"]["Crater Entry Point"]["extraScans"] = [
                    {
                        "position": [
                            -19.4009,
                            41.001,
                            2.805
                        ],
                        "combatVisible": True,
                        "text": phazon_hint_text,
                        "rotation": 45.0,
                        "isRed": True,
                        "logbookTitle": "Phazon Suit",
                        "logbookCategory": 5  # Artifacts
                    }
                ]
            except ValueError:
                pass  # Skip making the hint if Phazon Suit is not in the seed

        # strip extraneous info
        world_data = _remove_empty(world_data)
        for world_item in world_data.values():
            if "rooms" not in world_item:
                world_item["rooms"] = {}

        starting_memo = None
        extra_starting = item_names.additional_starting_equipment(self.configuration, db, self.patches)
        if extra_starting:
            starting_memo = ", ".join(extra_starting)

        if self.cosmetic_patches.open_map and self.configuration.elevators.is_vanilla:
            map_default_state = "visible"
        else:
            map_default_state = "default"

        credits_string = credits_spoiler.prime_trilogy_credits(
            self.configuration.major_items_configuration,
            self.description.all_patches,
            self.players_config,
            namer,
            "&push;&font=C29C51F1;&main-color=#89D6FF;Major Item Locations&pop;",
            "&push;&font=C29C51F1;&main-color=#33ffd6;{}&pop;",
        )

        artifacts = [
            db.resource_database.get_item(index)
            for index in prime_items.ARTIFACT_ITEMS
        ]
        hint_config = self.configuration.hints
        if hint_config.artifacts == ArtifactHintMode.DISABLED:
            resulting_hints = {art: f"{art.long_name} is lost somewhere on Tallon IV." for art in artifacts}
        else:
            resulting_hints = guaranteed_item_hint.create_guaranteed_hints_for_resources(
                self.description.all_patches,
                self.players_config, namer,
                hint_config.artifacts == ArtifactHintMode.HIDE_AREA,
                [db.resource_database.get_item(index) for index in prime_items.ARTIFACT_ITEMS],
                True,
            )

        # Tweaks
        ctwk_config = {}
        if self.configuration.small_samus:
            ctwk_config["playerSize"] = 0.3
            ctwk_config["morphBallSize"] = 0.3
            ctwk_config["easyLavaEscape"] = True

        if self.configuration.large_samus:
            ctwk_config["playerSize"] = 1.75

        if self.cosmetic_patches.use_hud_color:
            ctwk_config["hudColor"] = [
                self.cosmetic_patches.hud_color[0] / 255,
                self.cosmetic_patches.hud_color[1] / 255,
                self.cosmetic_patches.hud_color[2] / 255
            ]

        SUIT_ATTRIBUTES = ["powerDeg", "variaDeg", "gravityDeg", "phazonDeg"]
        suit_colors = {}
        for attribute, hue_rotation in zip(SUIT_ATTRIBUTES, self.cosmetic_patches.suit_color_rotations):
            if hue_rotation != 0:
                suit_colors[attribute] = hue_rotation

        starting_room = _name_for_start_location(db.world_list, self.patches.starting_location)

        starting_resources = self.patches.starting_resources()
        starting_items = {
            name: _starting_items_value_for(db.resource_database, starting_resources, index)
            for name, index in _STARTING_ITEM_NAME_TO_INDEX.items()
        }

        if not self.configuration.legacy_mode:
            idrone_config = {
                "eyeWaitInitialRandomTime": 0.0,
                "eyeWaitRandomTime": 0.0,
                "eyeStayUpRandomTime": 0.0,
                "resetContraptionRandomTime": 0.0,
                # ~~~ Justification for Divide by 2 ~~~
                # These Timer RNG values are normally re-rolled inbetween each of the 4 phases,
                # turning the zoid fight duration probability into a bell curve. With /2 we manipulate
                # the (now linear) probability characteristic to more often generate "average zoid fights"
                # while erring on the side of faster.
                "eyeWaitInitialMinimumTime": 8.0 + self.rng.random() * 5.0 / 2.0,
                "eyeWaitMinimumTime": 15.0 + self.rng.random() * 10.0 / 2.0,
                "eyeStayUpMinimumTime": 8.0 + self.rng.random() * 3.0 / 2.0,
                "resetContraptionMinimumTime": 3.0 + self.rng.random() * 3.0 / 2.0,
            }
        else:
            idrone_config = None

        if not self.configuration.legacy_mode:
            maze_seeds = [self.rng.choice(VANILLA_MAZE_SEEDS)]
        else:
            maze_seeds = None

        seed = self.description.get_seed_for_player(self.players_config.player_index)

        if self.configuration.legacy_mode:
            qol_cutscenes = LayoutCutsceneMode.ORIGINAL.value
        else:
            qol_cutscenes = self.configuration.qol_cutscenes.value

        boss_sizes = None
        random_enemy_sizes = False
        if self.configuration.enemy_attributes is not None:
            random_enemy_sizes = (
                    self.configuration.enemy_attributes.enemy_rando_range_scale_low != 1.0 or
                    self.configuration.enemy_attributes.enemy_rando_range_scale_low != 1.0
            )

        if self.configuration.random_boss_sizes and not random_enemy_sizes:
            def get_random_size(minimum, maximum):
                if self.rng.choice([True, False]):
                    temp = [self.rng.uniform(minimum, 1.0), self.rng.uniform(minimum, 1.0)]
                    return min(temp)
                else:
                    temp = [self.rng.uniform(1.0, maximum), self.rng.uniform(1.0, maximum)]
                    return max(temp)

            boss_sizes = {
                "parasiteQueen": get_random_size(0.1, 3.0),
                "incineratorDrone": get_random_size(0.2, 3.0),
                "adultSheegoth": get_random_size(0.1, 1.5),
                "thardus": get_random_size(0.05, 2.0),
                "elitePirate1": get_random_size(0.05, 2.3),
                "elitePirate2": get_random_size(0.05, 1.3),
                "elitePirate3": get_random_size(0.05, 2.0),
                "phazonElite": get_random_size(0.1, 2.0),
                "omegaPirate": get_random_size(0.05, 2.0),
                "Ridley": get_random_size(0.2, 1.5),
                "exo": get_random_size(0.15, 2.0),
                "essence": get_random_size(0.05, 2.25),
                "flaahgra": get_random_size(0.15, 3.3),
                "platedBeetle": get_random_size(0.05, 6.0),
                "cloakedDrone": get_random_size(0.05, 6.0),  # only scales width (lmao)
            }

        return {
            "seed": seed,
            "preferences": {
                "defaultGameOptions": self.get_default_game_options(),
                "qolGameBreaking": not self.configuration.legacy_mode,
                "qolCosmetic": not self.configuration.legacy_mode,
                "qolPickupScans": not self.configuration.legacy_mode,
                "qolCutscenes": qol_cutscenes,
                "mapDefaultState": map_default_state,
                "artifactHintBehavior": None,
                "automaticCrashScreen": True,
                "trilogyDiscPath": None,
                "quickplay": False,
                "quiet": False,
                "suitColors": suit_colors,
                "forceFusion": self.cosmetic_patches.force_fusion,
            },
            "gameConfig": {
                "resultsString": _create_results_screen_text(self.description),
                "bossSizes": boss_sizes,
                "noDoors": self.configuration.no_doors,
                "shufflePickupPosition": self.configuration.shuffle_item_pos,
                "shufflePickupPosAllRooms": False,  # functionality is handled in randovania as of v4.3
                "startingRoom": starting_room,
                "startingMemo": starting_memo,
                "warpToStart": self.configuration.warp_to_start,
                "springBall": self.configuration.spring_ball,
                "incineratorDroneConfig": idrone_config,
                "mazeSeeds": maze_seeds,
                "nonvariaHeatDamage": not self.configuration.legacy_mode,
                "staggeredSuitDamage": self.configuration.progressive_damage_reduction,
                "heatDamagePerSec": self.configuration.heat_damage,
                "autoEnabledElevators": not starting_resources.has_resource(scan_visor),
                "multiworldDolPatches": True,

                "disableItemLoss": True,  # Item Loss in Frigate
                "startingItems": starting_items,

                "etankCapacity": self.configuration.energy_per_tank,
                "itemMaxCapacity": {
                    "Energy Tank": db.resource_database.get_item("EnergyTank").max_capacity,
                    "Power Bomb": db.resource_database.get_item("PowerBomb").max_capacity,
                    "Missile": db.resource_database.get_item("Missile").max_capacity,
                    "Unknown Item 1": db.resource_database.multiworld_magic_item.max_capacity,
                },

                "mainPlazaDoor": self.configuration.main_plaza_door,
                "backwardsFrigate": self.configuration.backwards_frigate,
                "backwardsLabs": self.configuration.backwards_labs,
                "backwardsUpperMines": self.configuration.backwards_upper_mines,
                "backwardsLowerMines": self.configuration.backwards_lower_mines,
                "phazonEliteWithoutDynamo": self.configuration.phazon_elite_without_dynamo,

                "gameBanner": {
                    "gameName": "Metroid Prime: Randomizer",
                    "gameNameFull": f"Metroid Prime: Randomizer - {self.description.shareable_hash}",
                    "description": f"Seed Hash: {self.description.shareable_word_hash}",
                },
                "mainMenuMessage": "Randovania v{}\n{}".format(
                    randovania.VERSION,
                    self.description.shareable_word_hash
                ),

                "creditsString": credits_string,
                "artifactHints": {
                    artifact.long_name: text
                    for artifact, text in resulting_hints.items()
                },
                "artifactTempleLayerOverrides": {
                    artifact.long_name: not starting_resources.has_resource(artifact)
                    for artifact in artifacts
                },
            },
            "tweaks": ctwk_config,
            "levelData": world_data,
            "hasSpoiler": self.description.has_spoiler,
            "roomRandoMode": self.configuration.room_rando.value,

            "randEnemyAttributes": (
                self.configuration.enemy_attributes.as_json
                if self.configuration.enemy_attributes is not None
                else None
            ),

            # TODO
            # "externAssetsDir": path_to_converted_assets,
        }
