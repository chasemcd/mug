"""
PlayerGroupManager: Tracks player groups across scenes.

This module provides a mechanism to remember which players were matched together
in a GymScene, allowing subsequent GymScenes to re-match the same group of players.
Supports groups of any size (2 or more players).
"""

from __future__ import annotations

import dataclasses
import time
import uuid
import threading
from typing import TYPE_CHECKING

from interactive_gym.server import thread_utils
from interactive_gym.utils.typing import SubjectID, SceneID

if TYPE_CHECKING:
    pass


@dataclasses.dataclass
class PlayerGroup:
    """Represents a group of players from a completed game."""

    group_id: str
    subject_ids: set[SubjectID]
    created_at: float
    source_scene_id: SceneID
    is_active: bool = True


class PlayerGroupManager:
    """
    Manages player groups across scenes.

    This class tracks which players have been matched together in a game,
    allowing subsequent GymScenes to either require the same group or allow
    new matches via FIFO queue.

    Supports groups of any size (2 or more players).

    Key responsibilities:
    - Create groups when a game ends (groups are always tracked)
    - Look up group members for a subject when entering a new GymScene
    - Track which scene each subject is currently in (for disconnect handling)
    - Clean up groups when subjects disconnect
    """

    def __init__(self):
        # subject_id -> group_id
        self.subject_groups: thread_utils.ThreadSafeDict = thread_utils.ThreadSafeDict()

        # group_id -> PlayerGroup
        self.groups: thread_utils.ThreadSafeDict = thread_utils.ThreadSafeDict()

        # subject_id -> current scene_id (for disconnect handling)
        self.subject_scenes: thread_utils.ThreadSafeDict = thread_utils.ThreadSafeDict()

        # Lock for complex operations that need atomicity
        self.lock = threading.Lock()

    def create_group(
        self,
        subject_ids: list[SubjectID],
        scene_id: SceneID
    ) -> str:
        """
        Create or update a group from a completed game.

        Called when a game ends. If any subject already has a group,
        it will be updated to the new group.

        Args:
            subject_ids: List of subject IDs that were in the game together.
                        Can be 2 or more players.
            scene_id: The scene ID where the group was created.

        Returns:
            The group_id for the new group.
        """
        with self.lock:
            group_id = str(uuid.uuid4())

            # Remove subjects from any existing groups first
            for subject_id in subject_ids:
                self._remove_from_existing_group(subject_id)

            # Create new group
            group = PlayerGroup(
                group_id=group_id,
                subject_ids=set(subject_ids),
                created_at=time.time(),
                source_scene_id=scene_id,
                is_active=True,
            )

            self.groups[group_id] = group

            # Map each subject to this group
            for subject_id in subject_ids:
                self.subject_groups[subject_id] = group_id

            return group_id

    def _remove_from_existing_group(self, subject_id: SubjectID) -> None:
        """
        Remove a subject from their current group (if any).

        Must be called with self.lock held.
        """
        old_group_id = self.subject_groups.get(subject_id)
        if old_group_id and old_group_id in self.groups:
            old_group = self.groups[old_group_id]
            old_group.subject_ids.discard(subject_id)

            # If group is now empty or has only one subject, remove it
            if len(old_group.subject_ids) <= 1:
                # Clean up remaining subject's mapping
                for remaining_subject in old_group.subject_ids:
                    if remaining_subject in self.subject_groups:
                        del self.subject_groups[remaining_subject]
                del self.groups[old_group_id]

        if subject_id in self.subject_groups:
            del self.subject_groups[subject_id]

    def get_group_members(self, subject_id: SubjectID) -> list[SubjectID]:
        """
        Get the other group members for a subject, if any.

        Args:
            subject_id: The subject to find group members for.

        Returns:
            List of other group member subject IDs (excluding the querying subject).
            Empty list if no group exists.
        """
        group_id = self.subject_groups.get(subject_id)
        if not group_id or group_id not in self.groups:
            return []

        group = self.groups[group_id]
        if not group.is_active:
            return []

        return [sid for sid in group.subject_ids if sid != subject_id]

    def get_group_id(self, subject_id: SubjectID) -> str | None:
        """
        Get the group ID for a subject.

        Args:
            subject_id: The subject to find group for.

        Returns:
            The group_id or None if no group exists.
        """
        return self.subject_groups.get(subject_id)

    def get_all_group_members(self, subject_id: SubjectID) -> list[SubjectID]:
        """
        Get all members of a group including the querying subject.

        Args:
            subject_id: Any subject in the group.

        Returns:
            List of all subject IDs in the group (including querying subject).
            Empty list if no group exists.
        """
        group_id = self.subject_groups.get(subject_id)
        if not group_id or group_id not in self.groups:
            return []

        group = self.groups[group_id]
        return list(group.subject_ids)

    def get_group_size(self, subject_id: SubjectID) -> int:
        """
        Get the size of a subject's group.

        Args:
            subject_id: Any subject in the group.

        Returns:
            Number of members in the group, or 0 if no group exists.
        """
        group_id = self.subject_groups.get(subject_id)
        if not group_id or group_id not in self.groups:
            return 0

        return len(self.groups[group_id].subject_ids)

    def remove_from_group(self, subject_id: SubjectID) -> None:
        """
        Remove a subject from their group.

        This is called when a subject leaves an experiment.

        Args:
            subject_id: The subject to remove from their group.
        """
        with self.lock:
            self._remove_from_existing_group(subject_id)

    def remove_all_groups_from_scene(self, scene_id: SceneID) -> None:
        """
        Remove all groups that were created by a specific scene.

        Useful for cleanup when a scene is deactivated.

        Args:
            scene_id: The scene whose groups should be removed.
        """
        with self.lock:
            # Find all groups from this scene
            groups_to_remove = [
                group_id for group_id, group in self.groups.items()
                if group.source_scene_id == scene_id
            ]

            # Remove each group
            for group_id in groups_to_remove:
                group = self.groups.get(group_id)
                if group:
                    # Remove subject mappings
                    for subject_id in group.subject_ids:
                        if self.subject_groups.get(subject_id) == group_id:
                            del self.subject_groups[subject_id]
                    # Remove group
                    del self.groups[group_id]

    def update_subject_scene(
        self,
        subject_id: SubjectID,
        scene_id: SceneID | None
    ) -> None:
        """
        Track which scene a subject is currently in.

        Called when a subject advances to a new scene or disconnects.

        Args:
            subject_id: The subject whose scene changed.
            scene_id: The new scene ID, or None if leaving.
        """
        if scene_id is None:
            if subject_id in self.subject_scenes:
                del self.subject_scenes[subject_id]
        else:
            self.subject_scenes[subject_id] = scene_id

    def get_subject_scene(self, subject_id: SubjectID) -> SceneID | None:
        """
        Get the current scene for a subject.

        Args:
            subject_id: The subject to query.

        Returns:
            The scene_id or None if not tracked.
        """
        return self.subject_scenes.get(subject_id)

    def are_group_members_in_same_scene(self, subject_id: SubjectID) -> bool:
        """
        Check if all group members are in the same scene.

        Used for disconnect handling - only notify group members if they're
        in the same active scene.

        Args:
            subject_id: The subject to check group members for.

        Returns:
            True if all group members are in the same scene, False otherwise.
        """
        subject_scene = self.subject_scenes.get(subject_id)
        if not subject_scene:
            return False

        group_members = self.get_group_members(subject_id)
        if not group_members:
            return False

        for member_id in group_members:
            member_scene = self.subject_scenes.get(member_id)
            if member_scene != subject_scene:
                return False

        return True

    def cleanup_subject(self, subject_id: SubjectID) -> None:
        """
        Clean up all tracking for a subject when they disconnect.

        Called when a subject disconnects from the experiment entirely.

        Args:
            subject_id: The subject to clean up.
        """
        with self.lock:
            # Remove from group
            self._remove_from_existing_group(subject_id)

            # Remove scene tracking
            if subject_id in self.subject_scenes:
                del self.subject_scenes[subject_id]
