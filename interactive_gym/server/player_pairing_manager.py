"""
PlayerPairingManager: Tracks player pairings across scenes.

This module provides a mechanism to remember which players were matched together
in a GymScene, allowing subsequent GymScenes to re-match the same players.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
import threading
from typing import TYPE_CHECKING

from interactive_gym.server import utils
from interactive_gym.utils.typing import SubjectID, SceneID

if TYPE_CHECKING:
    pass


@dataclasses.dataclass
class PlayerPairing:
    """Represents a pairing between players from a completed game."""

    pairing_id: str
    subject_ids: set[SubjectID]
    created_at: float
    source_scene_id: SceneID
    is_active: bool = True


class PlayerPairingManager:
    """
    Manages player pairings across scenes.

    This singleton-style class tracks which players have been paired together
    and allows GymScenes to either maintain or sever those pairings.

    Key responsibilities:
    - Create pairings when a game ends with persist_player_ties=True
    - Look up partners for a subject when entering a new GymScene
    - Track which scene each subject is currently in (for disconnect handling)
    - Sever pairings when configured or when experiment ends
    """

    def __init__(self):
        # subject_id -> pairing_id
        self.subject_pairings: utils.ThreadSafeDict = utils.ThreadSafeDict()

        # pairing_id -> PlayerPairing
        self.pairings: utils.ThreadSafeDict = utils.ThreadSafeDict()

        # subject_id -> current scene_id (for disconnect handling)
        self.subject_scenes: utils.ThreadSafeDict = utils.ThreadSafeDict()

        # Lock for complex operations that need atomicity
        self.lock = threading.Lock()

    def create_pairing(
        self,
        subject_ids: list[SubjectID],
        scene_id: SceneID
    ) -> str:
        """
        Create a new pairing from a completed game.

        Called when a game ends and the scene has persist_player_ties=True.
        If any subject already has a pairing, it will be updated.

        Args:
            subject_ids: List of subject IDs that were in the game together.
            scene_id: The scene ID where the pairing was created.

        Returns:
            The pairing_id for the new pairing.
        """
        with self.lock:
            pairing_id = str(uuid.uuid4())

            # Remove subjects from any existing pairings first
            for subject_id in subject_ids:
                self._remove_from_existing_pairing(subject_id)

            # Create new pairing
            pairing = PlayerPairing(
                pairing_id=pairing_id,
                subject_ids=set(subject_ids),
                created_at=time.time(),
                source_scene_id=scene_id,
                is_active=True,
            )

            self.pairings[pairing_id] = pairing

            # Map each subject to this pairing
            for subject_id in subject_ids:
                self.subject_pairings[subject_id] = pairing_id

            return pairing_id

    def _remove_from_existing_pairing(self, subject_id: SubjectID) -> None:
        """
        Remove a subject from their current pairing (if any).

        Must be called with self.lock held.
        """
        old_pairing_id = self.subject_pairings.get(subject_id)
        if old_pairing_id and old_pairing_id in self.pairings:
            old_pairing = self.pairings[old_pairing_id]
            old_pairing.subject_ids.discard(subject_id)

            # If pairing is now empty or has only one subject, remove it
            if len(old_pairing.subject_ids) <= 1:
                # Clean up remaining subject's mapping
                for remaining_subject in old_pairing.subject_ids:
                    if remaining_subject in self.subject_pairings:
                        del self.subject_pairings[remaining_subject]
                del self.pairings[old_pairing_id]

        if subject_id in self.subject_pairings:
            del self.subject_pairings[subject_id]

    def get_partners(self, subject_id: SubjectID) -> list[SubjectID]:
        """
        Get the partners for a subject, if any.

        Args:
            subject_id: The subject to find partners for.

        Returns:
            List of partner subject IDs (excluding the querying subject).
            Empty list if no pairing exists.
        """
        pairing_id = self.subject_pairings.get(subject_id)
        if not pairing_id or pairing_id not in self.pairings:
            return []

        pairing = self.pairings[pairing_id]
        if not pairing.is_active:
            return []

        return [sid for sid in pairing.subject_ids if sid != subject_id]

    def get_pairing_id(self, subject_id: SubjectID) -> str | None:
        """
        Get the pairing ID for a subject.

        Args:
            subject_id: The subject to find pairing for.

        Returns:
            The pairing_id or None if no pairing exists.
        """
        return self.subject_pairings.get(subject_id)

    def get_all_pairing_members(self, subject_id: SubjectID) -> list[SubjectID]:
        """
        Get all members of a pairing including the querying subject.

        Args:
            subject_id: Any subject in the pairing.

        Returns:
            List of all subject IDs in the pairing (including querying subject).
            Empty list if no pairing exists.
        """
        pairing_id = self.subject_pairings.get(subject_id)
        if not pairing_id or pairing_id not in self.pairings:
            return []

        pairing = self.pairings[pairing_id]
        return list(pairing.subject_ids)

    def sever_pairing(self, subject_id: SubjectID) -> None:
        """
        Remove a subject from their pairing.

        This is called when a subject leaves an experiment or when
        ties are explicitly severed.

        Args:
            subject_id: The subject to remove from their pairing.
        """
        with self.lock:
            self._remove_from_existing_pairing(subject_id)

    def sever_all_pairings_from_scene(self, scene_id: SceneID) -> None:
        """
        Remove all pairings that were created by a specific scene.

        Useful for cleanup when a scene is deactivated with sever ties.

        Args:
            scene_id: The scene whose pairings should be removed.
        """
        with self.lock:
            # Find all pairings from this scene
            pairings_to_remove = [
                pairing_id for pairing_id, pairing in self.pairings.items()
                if pairing.source_scene_id == scene_id
            ]

            # Remove each pairing
            for pairing_id in pairings_to_remove:
                pairing = self.pairings.get(pairing_id)
                if pairing:
                    # Remove subject mappings
                    for subject_id in pairing.subject_ids:
                        if self.subject_pairings.get(subject_id) == pairing_id:
                            del self.subject_pairings[subject_id]
                    # Remove pairing
                    del self.pairings[pairing_id]

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

    def are_partners_in_same_scene(self, subject_id: SubjectID) -> bool:
        """
        Check if all partners are in the same scene.

        Used for disconnect handling - only notify partners if they're
        in the same active scene.

        Args:
            subject_id: The subject to check partners for.

        Returns:
            True if all partners are in the same scene, False otherwise.
        """
        subject_scene = self.subject_scenes.get(subject_id)
        if not subject_scene:
            return False

        partners = self.get_partners(subject_id)
        if not partners:
            return False

        for partner_id in partners:
            partner_scene = self.subject_scenes.get(partner_id)
            if partner_scene != subject_scene:
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
            # Remove from pairing
            self._remove_from_existing_pairing(subject_id)

            # Remove scene tracking
            if subject_id in self.subject_scenes:
                del self.subject_scenes[subject_id]
