from __future__ import annotations

import collections
import copy
import dataclasses
import functools
import random
from typing import Any

import numpy as np
from cogrid import cogrid_env
from cogrid.core import actions as cogrid_actions
from cogrid.core import grid_object, grid_utils, layouts, reward
from cogrid.core import typing
from cogrid.core import typing as cogrid_typing
from cogrid.core.grid import Grid
from cogrid.envs import overcooked, registry
from cogrid.envs.overcooked import (overcooked, overcooked_features,
                                    overcooked_grid_objects)
from cogrid.envs.overcooked import rewards as overcooked_rewards
from cogrid.feature_space import feature, feature_space, features

from mug.rendering import Surface


class BehaviorFeatures(feature.Feature):
    """A feature that provides the weight coefficient for each reward function."""

    def __init__(self, **kwargs):
        super().__init__(
            low=-np.inf,
            high=np.inf,
            shape=(4,),
            name="overcooked_behavior_features",
            **kwargs,
        )

    def generate(self, env: cogrid_env.CoGridEnv, player_id, **kwargs):
        encoding = np.zeros(self.shape, dtype=np.float32)

        reward_weights = env.reward_weights[player_id]
        for i, reward_id in enumerate(reward_weights.keys()):
            encoding[i] = reward_weights[reward_id]

        return encoding


class OvercookedCollectedBehaviorFeatures(feature.Feature):
    """
    A wrapper class to create all overcooked features as a single array.
    """

    def __init__(self, env: cogrid_env.CoGridEnv, **kwargs):
        max_num_pots = 2
        max_num_agents = len(env.agent_ids)

        self.shared_features = [
            features.AgentDir(),
            overcooked_features.OvercookedInventory(),
            overcooked_features.NextToCounter(),
            overcooked_features.NextToPot(),
            overcooked_features.ClosestObj(
                focal_object_type=overcooked_grid_objects.Onion, n=4
            ),
            overcooked_features.ClosestObj(
                focal_object_type=overcooked_grid_objects.Plate, n=4
            ),
            overcooked_features.ClosestObj(
                focal_object_type=overcooked_grid_objects.PlateStack, n=2
            ),
            overcooked_features.ClosestObj(
                focal_object_type=overcooked_grid_objects.OnionStack, n=2
            ),
            overcooked_features.ClosestObj(
                focal_object_type=overcooked_grid_objects.OnionSoup, n=4
            ),
            overcooked_features.ClosestObj(
                focal_object_type=overcooked_grid_objects.DeliveryZone, n=2
            ),
            overcooked_features.ClosestObj(
                focal_object_type=grid_object.Counter, n=4
            ),
            overcooked_features.OrderedPotFeatures(num_pots=max_num_pots),
            overcooked_features.DistToOtherPlayers(
                num_other_players=max_num_agents - 1
            ),
            features.AgentPosition(),
            features.CanMoveDirection(),
        ]

        self.individual_features = [
            BehaviorFeatures(),
            overcooked_features.LayoutID(),
        ]

        full_shape = max_num_agents * np.sum(
            [feature.shape for feature in self.shared_features]
        ) + np.sum([feature.shape for feature in self.individual_features])

        super().__init__(
            low=-np.inf,
            high=np.inf,
            shape=(full_shape,),
            name="overcooked_behavior_features",
            **kwargs,
        )

    def generate(
        self, env: cogrid_env.CoGridEnv, player_id, **kwargs
    ) -> np.ndarray:
        player_encodings = [self.generate_player_encoding(env, player_id)]

        for pid in env.agent_ids:
            if pid == player_id:
                continue
            player_encodings.append(self.generate_player_encoding(env, pid))

        encoding = np.hstack(player_encodings).astype(np.float32)
        encoding = np.hstack(
            [encoding, self.generate_individual_encoding(env, player_id)]
        )
        assert np.array_equal(self.shape, encoding.shape)

        return encoding

    def generate_player_encoding(
        self, env: cogrid_env.CoGridEnv, player_id: str | int
    ) -> np.ndarray:
        encoded_features = []
        for feature in self.shared_features:
            encoded_features.append(feature.generate(env, player_id))

        return np.hstack(encoded_features)

    def generate_individual_encoding(
        self, env: cogrid_env.CoGridEnv, player_id: str | int
    ) -> np.ndarray:
        encoded_features = []
        for feature in self.individual_features:
            encoded_features.append(feature.generate(env, player_id))

        return np.hstack(encoded_features)


feature_space.register_feature(
    "overcooked_behavior_features", OvercookedCollectedBehaviorFeatures
)


class OvercookedBehaviorVFFeatures(feature.Feature):

    def __init__(self, env: cogrid_env.CoGridEnv, **kwargs):

        self.features = [BehaviorFeatures()]

        full_shape = np.sum([feature.shape for feature in self.features])

        super().__init__(
            low=-np.inf,
            high=np.inf,
            shape=(full_shape,),
            name="vf_features",
            **kwargs,
        )

    def generate(
        self, env: cogrid_env.CoGridEnv, player_id, **kwargs
    ) -> np.ndarray:
        player_encodings = []

        for pid in env.agent_ids:
            if pid == player_id:
                continue
            player_encodings.append(self.generate_player_encoding(env, pid))

        encoding = np.hstack(player_encodings).astype(np.float32)

        assert np.array_equal(self.shape, encoding.shape)

        return encoding

    def generate_player_encoding(
        self, env: cogrid_env.CoGridEnv, player_id: str | int
    ) -> np.ndarray:
        encoded_features = []
        for feature in self.features:
            encoded_features.append(feature.generate(env, player_id))

        return np.hstack(encoded_features)


feature_space.register_feature(
    "overcooked_vf_features", OvercookedBehaviorVFFeatures
)


class SoupDeliveryActReward(reward.Reward):
    """Provide a reward for delivery an OnionSoup to a DeliveryZone."""

    def __init__(
        self, agent_ids: list[str | int], coefficient: float = 1.0, **kwargs
    ):
        super().__init__(
            name="delivery_act_reward",
            agent_ids=agent_ids,
            coefficient=coefficient,
            **kwargs,
        )

    def calculate_reward(
        self,
        state: Grid,
        agent_actions: dict[cogrid_typing.AgentID, cogrid_typing.ActionType],
        new_state: Grid,
    ) -> dict[cogrid_typing.AgentID, float]:
        """Calcaute the reward for delivering a soup dish.

        :param state: The previous state of the grid.
        :type state: Grid
        :param actions: Actions taken by each agent in the previous state of the grid.
        :type actions: dict[int  |  str, int  |  float]
        :param new_state: The new state of the grid.
        :type new_state: Grid
        """
        # Reward is shared among all agents, so calculate once
        # then distribute to all agents

        individual_rewards = {agent_id: 0 for agent_id in self.agent_ids}

        for agent_id, action in agent_actions.items():
            # Check if agent is performing a PickupDrop action
            if action != cogrid_actions.Actions.PickupDrop:
                continue

            # Check if an agent is holding an OnionSoup
            agent = state.grid_agents[agent_id]
            agent_holding_soup = any(
                [
                    isinstance(obj, overcooked_grid_objects.OnionSoup)
                    for obj in agent.inventory
                ]
            )

            # Check if the agent is facing a delivery zone
            fwd_pos = agent.front_pos
            fwd_cell = state.get(*fwd_pos)
            agent_facing_delivery = isinstance(
                fwd_cell, overcooked_grid_objects.DeliveryZone
            )

            if agent_holding_soup and agent_facing_delivery:
                individual_rewards[agent_id] += self.coefficient

        return individual_rewards


reward.register_reward("delivery_act_reward", SoupDeliveryActReward)


class OvercookedRewardEnv(overcooked.Overcooked):
    def __init__(self, config, render_mode=None, **kwargs):
        overcooked.Overcooked.__init__(
            self, config, render_mode=render_mode, **kwargs
        )
        self.observation_space = self.observation_spaces[0]
        self.action_space = self.action_spaces[0]
        self.sample_delivery_reward = config.get(
            "sample_delivery_reward", False
        )
        self.default_behavior_weights = config.get(
            "behavior_weights",
            {
                agent_id: {
                    "delivery_reward": 1,
                    "delivery_act_reward": 0,
                    "onion_in_pot_reward": 0,
                    "soup_in_dish_reward": 0,
                }
                for agent_id in self.agents
            },
        )
        self.reward_weights: dict[cogrid_typing.AgentID, dict[str, float]] = (
            copy.deepcopy(self.default_behavior_weights)
        )

        self.unshaped_proportion = config.get("unshaped_proportion", 0.95)

        self.enable_weight_randomization = config.get(
            "enable_weight_randomization", True
        )

        # Surface rendering setup
        self.surface = Surface(width=WIDTH, height=HEIGHT)
        self.surface.register_atlas(
            "terrain",
            img_path=f"{ASSET_PATH}/terrain.png",
            json_path=f"{ASSET_PATH}/terrain.json",
        )
        self.surface.register_atlas(
            "chefs",
            img_path=f"{ASSET_PATH}/chefs.png",
            json_path=f"{ASSET_PATH}/chefs.json",
        )
        self.surface.register_atlas(
            "objects",
            img_path=f"{ASSET_PATH}/objects.png",
            json_path=f"{ASSET_PATH}/objects.json",
        )

    def on_reset(self) -> None:
        """Generate new reward weights every reset."""
        super().on_reset()
        self._pending_surface_reset = True

        if not self.enable_weight_randomization:
            self.reward_weights = {
                agent_id: copy.deepcopy(self.default_behavior_weights[agent_id])
                for agent_id in self._agent_ids
            }
            return

        reward_weights = {agent_id: {} for agent_id in self.agent_ids}

        for agent_id in self.agents:
            for reward_id in self.default_behavior_weights[agent_id].keys():
                if (
                    reward_id == "delivery_reward"
                    and not self.sample_delivery_reward
                ) or np.random.random() < self.unshaped_proportion:
                    weight = self.default_behavior_weights[agent_id][reward_id]
                    reward_weights[agent_id][reward_id] = weight
                else:
                    sampled_weight = (
                        np.random.normal()
                        if reward_id != "delivery_reward"
                        else np.random.normal(loc=1.0, scale=1.0)
                    )

                    reward_weights[agent_id][reward_id] = sampled_weight

        self.reward_weights = reward_weights

    def compute_rewards(
        self,
    ) -> None:
        """Compute the per agent and per component rewards for the current state transition
        using the reward modules provided in the environment configuration.

        The rewards are added to self.per_agent_rewards and self.per_component_rewards.
        """

        for reward in self.rewards:
            calculated_rewards = reward.calculate_reward(
                state=self.prev_grid,
                agent_actions=self.prev_actions,
                new_state=self.grid,
            )

            # Add component rewards to per agent reward
            # NOTE(chase): We're not multiplying by the reward weights here
            # because MUG will display the returned value
            # and we only want to display the delivery reward.
            for agent_id, reward_value in calculated_rewards.items():
                self.per_agent_reward[agent_id] += reward_value * int(
                    isinstance(reward, overcooked_rewards.SoupDeliveryReward)
                )

            # Save reward by component
            self.per_component_reward[reward.name] = calculated_rewards

    def step(self, actions: dict) -> tuple[
        dict,
        dict[Any, float],
        dict[Any, bool],
        dict[Any, bool],
        dict[Any, dict[Any, Any]],
    ]:
        """Add in __all__ to terminateds and truncates"""
        obs, rewards, terminateds, truncateds, infos = super().step(actions)

        terminateds["__all__"] = all(terminateds.values())
        truncateds["__all__"] = all(truncateds.values())
        return obs, rewards, terminateds, truncateds, infos


reward.register_reward(
    "onion_in_pot_reward_1.0coeff",
    functools.partial(overcooked_rewards.OnionInPotReward, coefficient=1.0),
)

reward.register_reward(
    "soup_in_dish_reward_1.0coeff",
    functools.partial(overcooked_rewards.SoupInDishReward, coefficient=1.0),
)


def get_x_y(
    pos: tuple[int, int], game_height: int, game_width: int
) -> tuple[int, int]:
    col, row = pos
    x = row * TILE_SIZE / game_width
    y = col * TILE_SIZE / game_height
    return x, y


ASSET_PATH = "static/assets/overcooked/sprites"
TILE_SIZE = 45
WIDTH = 10 * TILE_SIZE
HEIGHT = 7 * TILE_SIZE
DIR_TO_CARDINAL_DIRECTION = {
    0: "EAST",
    1: "SOUTH",
    2: "WEST",
    3: "NORTH",
}
PLAYER_COLORS = {0: "blue", 1: "green"}


class OvercookedEnv(OvercookedRewardEnv):

    def get_infos(self, **kwargs):
        """Add the agent positions and directions to the infos dictionary"""
        infos = super().get_infos(**kwargs)

        for agent_id, agent in self.grid.grid_agents.items():
            row, col = agent.pos
            infos[agent_id]["row"] = int(row)
            infos[agent_id]["col"] = int(col)
            infos[agent_id]["direction"] = int(agent.dir)
            infos[agent_id]["layout_id"] = self.current_layout_id

        return infos

    def render(self):
        # Static objects (persistent, only sent on first frame or change)
        for obj in self.grid.grid:
            if obj is None:
                continue

            if (
                isinstance(obj, grid_object.Counter)
                or isinstance(obj, grid_object.Wall)
                or isinstance(obj, overcooked_grid_objects.Pot)
            ):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="counter.png",
                    persistent=True,
                    relative=True,
                    depth=-2,
                )

            if isinstance(obj, overcooked_grid_objects.DeliveryZone):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="serve.png",
                    persistent=True,
                    relative=True,
                )

            if isinstance(obj, overcooked_grid_objects.PlateStack):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="dishes.png",
                    persistent=True,
                    relative=True,
                )
            elif isinstance(obj, overcooked_grid_objects.OnionStack):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="onions.png",
                    persistent=True,
                    relative=True,
                )
            elif isinstance(obj, overcooked_grid_objects.Pot):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=f"{obj.uuid}-pot",
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="pot.png",
                    persistent=True,
                    relative=True,
                )

        # Dynamic objects
        for obj in self.grid.grid:
            if obj is None:
                continue

            if obj.can_place_on and obj.obj_placed_on is not None:
                placed_obj = obj.obj_placed_on
                self._draw_dynamic_object(placed_obj)

            self._draw_dynamic_object(obj)

        # Agent sprites
        for i, agent_obj in enumerate(self.grid.grid_agents.values()):
            x, y = get_x_y(agent_obj.pos, HEIGHT, WIDTH)
            held_object_name = ""
            if agent_obj.inventory:
                assert (
                    len(agent_obj.inventory) == 1
                ), "Rendering not supported for inventory > 1."
                held_obj = agent_obj.inventory[0]
                if isinstance(held_obj, overcooked_grid_objects.Onion):
                    held_object_name = "-onion"
                elif isinstance(held_obj, overcooked_grid_objects.OnionSoup):
                    held_object_name = "-soup-onion"
                elif isinstance(held_obj, overcooked_grid_objects.Plate):
                    held_object_name = "-dish"

            dir = DIR_TO_CARDINAL_DIRECTION[agent_obj.dir]
            self.surface.image(
                id=f"agent-{i}-sprite",
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="chefs",
                frame=f"{dir}{held_object_name}.png",
                tween_duration=75,
                relative=True,
            )
            self.surface.image(
                id=f"agent-{i}-hat-sprite",
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="chefs",
                frame=f"{dir}-{PLAYER_COLORS[i]}hat.png",
                tween_duration=75,
                relative=True,
                depth=2,
            )

        result = self.surface.commit().to_dict()

        # After commit, if a reset is pending, clear the committed persistent
        # cache so the NEXT render() call retransmits all objects.
        # This handles the cogrid base class calling render() during reset().
        if getattr(self, "_pending_surface_reset", False):
            self.surface._committed_persistent.clear()
            self.surface._ephemeral_buffer.clear()
            self._pending_surface_reset = False

        return result

    def _draw_dynamic_object(self, obj):
        """Draw a dynamic (non-persistent) object onto the surface."""
        if isinstance(obj, overcooked_grid_objects.Pot):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            if not obj.objects_in_pot:
                return
            status = "cooked" if obj.cooking_timer == 0 else "cooking"
            if status == "cooking":
                frame = f"soup-onion-{len(obj.objects_in_pot)}-cooking.png"
            else:
                frame = "soup-onion-cooked.png"

            self.surface.image(
                id=f"{obj.uuid}-contents",
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame=frame,
                relative=True,
                depth=1,
            )

            if status == "cooking" and len(obj.objects_in_pot) == 3:
                self.surface.text(
                    id="time_left",
                    text=f"{obj.cooking_timer:02d}",
                    x=x,
                    y=y,
                    size=14,
                    color="red",
                    relative=True,
                )
        elif isinstance(obj, overcooked_grid_objects.Onion):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="onion.png",
                relative=True,
                depth=1,
            )
        elif isinstance(obj, overcooked_grid_objects.Plate):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="dish.png",
                relative=True,
                depth=1,
            )
        elif isinstance(obj, overcooked_grid_objects.OnionSoup):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="soup-onion-dish.png",
                relative=True,
                depth=1,
            )


class ScaledFullMapEncoding(features.FullMapEncoding):
    def generate(self, env, player_id, **kwargs):
        encoding = super().generate(env, player_id, **kwargs)
        return encoding / 100.0


feature_space.register_feature(
    "scaled_full_map_encoding", ScaledFullMapEncoding
)


overcooked_config = {
    "name": "overcooked",
    "num_agents": 2,
    "action_set": "cardinal_actions",
    "features": {
        0: [],
        1: [
            "overcooked_behavior_features",
            # "overcooked_vf_features",
            "scaled_full_map_encoding",
        ],
    },
    "rewards": [
        "delivery_reward",
        "delivery_act_reward",
        "onion_in_pot_reward_1.0coeff",
        "soup_in_dish_reward_1.0coeff",
    ],
    "grid": {"layout": "overcooked_counter_circuit_v0"},
    "scope": "overcooked",
    "max_steps": 1350,
    "unshaped_proportion": 1.0,
    "enable_weight_randomization": False,
    "behavior_weights": {
        agent_id: {
            "delivery_reward": 1,
            "delivery_act_reward": 0,
            "onion_in_pot_reward": 0,
            "soup_in_dish_reward": 0,
        }
        for agent_id in range(2)
    },
}

registry.register(
    environment_id="Overcooked-BehaviorFeatures-CounterCircuit-EnvToRender",
    env_class=functools.partial(OvercookedEnv, config=overcooked_config),
)

env = registry.make(
    "Overcooked-BehaviorFeatures-CounterCircuit-EnvToRender", render_mode="mug"
)
