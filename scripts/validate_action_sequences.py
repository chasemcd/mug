#!/usr/bin/env python3
"""
Validate and analyze action sequences between paired players in P2P multiplayer games.

This script loads all CSV data files from a scene directory and:
1. Validates that paired players have identical action sequences
2. Counts action mismatches between paired files
3. Plots average reward by pair across episodes
4. Plots the four reward columns from infos to confirm parity between paired participants

Usage:
    python scripts/validate_action_sequences.py data/cramped_room_hh
    python scripts/validate_action_sequences.py data/cramped_room_hh --verbose
    python scripts/validate_action_sequences.py data/cramped_room_hh --no-plot

Compare mode (Phase 39: VERIFY-01):
    python scripts/validate_action_sequences.py --compare file1.csv file2.csv
    python scripts/validate_action_sequences.py --compare file1.csv file2.csv --verbose
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

# Optional matplotlib import for plotting
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# The four reward columns from infos to compare
REWARD_INFO_KEYS = [
    "delivery_reward",
    "delivery_act_reward",
    "onion_in_pot_reward",
    "soup_in_dish_reward",
]

# Columns expected to differ between players (local metrics, not game state)
# These should be excluded from parity checks as they measure client-local data
COLUMNS_EXCLUDE_FROM_COMPARE = {
    "timestamp",        # Local timestamp differs between clients
    "rollbackEvents",   # Each player has their own rollback perspective
    "wasSpeculative",   # Speculative state tracking is client-local
}


def load_csv(filepath: Path) -> tuple[list[str], list[dict]]:
    """Load a CSV file and return (headers, list of row dicts)."""
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows


def compare_files(file1: Path, file2: Path, verbose: bool = False) -> int:
    """Compare two export files and report divergences.

    Phase 39: VERIFY-01 - Offline validation for post-experiment analysis.

    Returns exit code: 0 if identical, 1 if different.
    """
    headers1, rows1 = load_csv(file1)
    headers2, rows2 = load_csv(file2)

    errors = []
    warnings = []

    # Check row counts - must be exactly equal
    # Both clients should terminate at the same frame (max_steps or terminal event)
    if len(rows1) != len(rows2):
        errors.append(f"Row count mismatch: {file1.name} has {len(rows1)} rows, {file2.name} has {len(rows2)} rows")

    # Check column sets
    if set(headers1) != set(headers2):
        only_in_1 = set(headers1) - set(headers2)
        only_in_2 = set(headers2) - set(headers1)
        if only_in_1:
            errors.append(f"Columns only in {file1.name}: {only_in_1}")
        if only_in_2:
            errors.append(f"Columns only in {file2.name}: {only_in_2}")

    # Compare common columns (excluding expected differences)
    common_cols = (set(headers1) & set(headers2)) - COLUMNS_EXCLUDE_FROM_COMPARE
    min_rows = min(len(rows1), len(rows2))

    divergences = defaultdict(list)
    for i in range(min_rows):
        for col in common_cols:
            val1 = rows1[i].get(col, "")
            val2 = rows2[i].get(col, "")
            if val1 != val2:
                divergences[col].append((i, val1, val2))

    # Report divergences
    if divergences:
        for col, diffs in sorted(divergences.items()):
            errors.append(f"Column '{col}' has {len(diffs)} divergences")
            if verbose:
                for idx, val1, val2 in diffs[:5]:
                    errors.append(f"  Row {idx}: {file1.name}={val1}, {file2.name}={val2}")
                if len(diffs) > 5:
                    errors.append(f"  ... and {len(diffs) - 5} more divergences")

    # Print results
    print(f"Comparing: {file1.name} vs {file2.name}")
    print("=" * 70)
    print(f"Rows: {len(rows1)} vs {len(rows2)}")
    print(f"Columns: {len(headers1)} vs {len(headers2)}")
    print()

    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"  {warning}")
        print()

    if errors:
        print("DIVERGENCES FOUND:")
        for error in errors:
            print(f"  {error}")
        return 1
    else:
        print("FILES ARE IDENTICAL")
        return 0


def load_episode_data(data_dir: Path) -> dict:
    """Load all episode CSVs and group by player pairs.

    Returns a dict mapping pair_key -> [(subject_id, rows, headers, filename, episode_num), ...]
    where pair_key is a sorted tuple of subject IDs that played together.
    """
    data_dir = Path(data_dir)
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    # Load all CSVs
    csv_files = list(data_dir.glob("*_ep*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No episode CSV files found in {data_dir}")

    # Group by pairs and episode
    pairs = defaultdict(list)

    for csv_path in csv_files:
        # Extract subject_id and episode from filename
        # Format: {subject_id}_ep{episode_num}.csv
        filename = csv_path.stem
        parts = filename.rsplit("_ep", 1)
        if len(parts) != 2:
            print(f"Warning: Skipping file with unexpected name format: {csv_path.name}")
            continue

        subject_id = parts[0]
        try:
            episode_num = int(parts[1])
        except ValueError:
            print(f"Warning: Could not parse episode number from {csv_path.name}")
            continue

        # Load the CSV
        headers, rows = load_csv(csv_path)

        if not rows:
            print(f"Warning: Empty CSV file: {csv_path.name}")
            continue

        # Get the paired player subjects from the first row
        player_0 = rows[0].get("player_subjects.0")
        player_1 = rows[0].get("player_subjects.1")

        if not player_0 or not player_1:
            print(f"Warning: Missing player_subjects in {csv_path.name}")
            continue

        # Create a pair key (sorted so order doesn't matter)
        pair_key = tuple(sorted([str(player_0), str(player_1)]))

        pairs[pair_key].append((subject_id, rows, headers, csv_path.name, episode_num))

    return pairs


def calculate_total_reward(rows: list[dict]) -> float:
    """Calculate total reward (sum of rewards.0 and rewards.1) for an episode."""
    total = 0.0
    for row in rows:
        try:
            r0 = float(row.get("rewards.0", 0) or 0)
            r1 = float(row.get("rewards.1", 0) or 0)
            total += r0 + r1
        except (ValueError, TypeError):
            pass
    return total


def extract_info_reward_series(rows: list[dict], agent_id: str, reward_key: str) -> list[float]:
    """Extract a time series of a specific reward from infos.

    Handles both old format (infos.0 = stringified dict) and new flattened format (infos.0.key).
    """
    values = []
    # Try new flattened format first: infos.{agent_id}.{reward_key}
    flat_key = f"infos.{agent_id}.{reward_key}"

    for row in rows:
        val = row.get(flat_key)
        if val is not None:
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                values.append(0.0)
        else:
            # Fall back to old format - infos.{agent_id} contains stringified dict
            old_key = f"infos.{agent_id}"
            info_str = row.get(old_key, "")
            if info_str and isinstance(info_str, str):
                # Parse the stringified dict (it's Python dict syntax, not JSON)
                try:
                    # Safe eval for dict-like strings
                    import ast
                    info_dict = ast.literal_eval(info_str)
                    values.append(float(info_dict.get(reward_key, 0)))
                except (ValueError, SyntaxError):
                    values.append(0.0)
            else:
                values.append(0.0)

    return values


def count_action_mismatches(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """Count action mismatches between two paired files.

    Returns dict with mismatch counts for each action column.
    """
    min_rows = min(len(rows_a), len(rows_b))
    action_cols = ["actions.0", "actions.1"]

    mismatches = {}
    for col in action_cols:
        count = 0
        for i in range(min_rows):
            val_a = rows_a[i].get(col, "")
            val_b = rows_b[i].get(col, "")
            if val_a != val_b:
                count += 1
        mismatches[col] = count

    # Also count row count difference
    mismatches["row_count_diff"] = abs(len(rows_a) - len(rows_b))

    return mismatches


def validate_pair(
    subject_a: str, rows_a: list[dict], file_a: str,
    subject_b: str, rows_b: list[dict], file_b: str,
    verbose: bool = False
) -> tuple[bool, list[str], dict]:
    """Validate that two paired players have identical action sequences.

    Returns (is_valid, list of error messages, mismatch_counts)
    """
    errors = []
    mismatch_counts = count_action_mismatches(rows_a, rows_b)

    # Check row counts
    if len(rows_a) != len(rows_b):
        errors.append(f"Row count mismatch: {file_a} has {len(rows_a)} rows, {file_b} has {len(rows_b)} rows")

    # Compare on the overlapping rows
    min_rows = min(len(rows_a), len(rows_b))

    # Columns to validate
    action_cols = ["actions.0", "actions.1"]
    reward_cols = ["rewards.0", "rewards.1"]
    terminated_cols = ["terminateds.0", "terminateds.1", "terminateds.__all__"]
    truncated_cols = ["truncateds.0", "truncateds.1", "truncateds.__all__"]
    time_cols = ["t", "episode_num"]

    all_validate_cols = action_cols + reward_cols + terminated_cols + truncated_cols + time_cols

    for col in all_validate_cols:
        if col not in rows_a[0] or col not in rows_b[0]:
            errors.append(f"Missing column {col} in one or both files")
            continue

        # Compare values
        mismatches = []
        for i in range(min_rows):
            val_a = rows_a[i].get(col, "")
            val_b = rows_b[i].get(col, "")

            if val_a != val_b:
                mismatches.append((i, val_a, val_b))

        if mismatches:
            errors.append(f"Column '{col}' has {len(mismatches)} mismatches")
            if verbose:
                for idx, val_a, val_b in mismatches[:5]:  # Show first 5
                    errors.append(f"  Row {idx}: {file_a}={val_a}, {file_b}={val_b}")
                if len(mismatches) > 5:
                    errors.append(f"  ... and {len(mismatches) - 5} more mismatches")

    return len(errors) == 0, errors, mismatch_counts


def analyze_pairs(pairs: dict, verbose: bool = False) -> tuple[dict, dict, dict, dict]:
    """Analyze all pairs and return validation results, rewards, mismatches, and raw data.

    Returns:
        validation_results: {pair_key: {episode: (is_valid, errors)}}
        rewards_by_pair: {pair_key: {episode: avg_reward}}
        mismatches_by_pair: {pair_key: {episode: mismatch_counts}}
        raw_episode_data: {pair_key: {episode: [(subject_a, rows_a), (subject_b, rows_b)]}}
    """
    validation_results = defaultdict(dict)
    rewards_by_pair = defaultdict(dict)
    mismatches_by_pair = defaultdict(dict)
    raw_episode_data = defaultdict(dict)

    for pair_key, pair_files in pairs.items():
        # Group files by episode
        episodes = defaultdict(list)
        for subject_id, rows, headers, filename, episode_num in pair_files:
            episodes[episode_num].append((subject_id, rows, headers, filename))

        for episode_num, episode_files in episodes.items():
            if len(episode_files) != 2:
                print(f"Warning: Expected 2 files for pair {pair_key} episode {episode_num}, found {len(episode_files)}")
                continue

            subject_a, rows_a, _, file_a = episode_files[0]
            subject_b, rows_b, _, file_b = episode_files[1]

            # Store raw data for plotting
            raw_episode_data[pair_key][episode_num] = [
                (subject_a, rows_a, file_a),
                (subject_b, rows_b, file_b)
            ]

            # Validate
            is_valid, errors, mismatch_counts = validate_pair(
                subject_a, rows_a, file_a,
                subject_b, rows_b, file_b,
                verbose=verbose
            )
            validation_results[pair_key][episode_num] = (is_valid, errors)
            mismatches_by_pair[pair_key][episode_num] = mismatch_counts

            # Calculate average reward (average of both players' total rewards)
            reward_a = calculate_total_reward(rows_a)
            reward_b = calculate_total_reward(rows_b)
            avg_reward = (reward_a + reward_b) / 2
            rewards_by_pair[pair_key][episode_num] = avg_reward

    return validation_results, rewards_by_pair, mismatches_by_pair, raw_episode_data


def plot_info_rewards_comparison(raw_episode_data: dict, output_path: Path = None):
    """Plot the four reward columns from infos comparing both participants in each pair."""
    if not HAS_MATPLOTLIB:
        print("\nWarning: matplotlib not available, skipping info reward plots")
        return

    # For each pair and episode, create a comparison plot
    for pair_key, episodes in sorted(raw_episode_data.items()):
        pair_short = f"{pair_key[0][:8]}...{pair_key[1][:8]}"

        for episode_num, episode_data in sorted(episodes.items()):
            subject_a, rows_a, file_a = episode_data[0]
            subject_b, rows_b, file_b = episode_data[1]

            # Create a 2x4 subplot: top row for agent 0, bottom row for agent 1
            fig, axes = plt.subplots(2, 4, figsize=(16, 8))
            fig.suptitle(f"Info Rewards Comparison - {pair_short} - Episode {episode_num}", fontsize=14)

            for agent_idx, agent_id in enumerate(["0", "1"]):
                for col_idx, reward_key in enumerate(REWARD_INFO_KEYS):
                    ax = axes[agent_idx, col_idx]

                    # Extract series from both files
                    series_a = extract_info_reward_series(rows_a, agent_id, reward_key)
                    series_b = extract_info_reward_series(rows_b, agent_id, reward_key)

                    # Plot both series
                    timesteps_a = list(range(len(series_a)))
                    timesteps_b = list(range(len(series_b)))

                    ax.plot(timesteps_a, series_a, label=f"{subject_a[:8]}...", alpha=0.7, linewidth=1)
                    ax.plot(timesteps_b, series_b, label=f"{subject_b[:8]}...", alpha=0.7, linewidth=1, linestyle='--')

                    ax.set_title(f"Agent {agent_id}: {reward_key}", fontsize=10)
                    ax.set_xlabel("Timestep", fontsize=8)
                    ax.set_ylabel("Value", fontsize=8)
                    ax.legend(fontsize=7)
                    ax.grid(True, alpha=0.3)

                    # Check for mismatches
                    min_len = min(len(series_a), len(series_b))
                    mismatches = sum(1 for i in range(min_len) if series_a[i] != series_b[i])
                    if mismatches > 0 or len(series_a) != len(series_b):
                        ax.set_facecolor('#fff0f0')  # Light red background for mismatches
                        ax.set_title(f"Agent {agent_id}: {reward_key} ({mismatches} mismatches)", fontsize=10, color='red')

            plt.tight_layout()

            if output_path:
                # Save each episode to a separate file
                base_path = Path(output_path)
                episode_path = base_path.parent / f"{base_path.stem}_ep{episode_num}_rewards{base_path.suffix}"
                plt.savefig(episode_path, dpi=150, bbox_inches='tight')
                print(f"  Saved info rewards plot: {episode_path}")
            else:
                plt.show()

            plt.close(fig)


def plot_results(rewards_by_pair: dict, mismatches_by_pair: dict, output_path: Path = None):
    """Plot rewards over episodes and mismatch counts."""
    if not HAS_MATPLOTLIB:
        print("\nWarning: matplotlib not available, skipping plots")
        return

    fig, axes = plt.subplots(2, 1, figsize=(12, 10))

    # Plot 1: Average reward by pair over episodes
    ax1 = axes[0]
    for i, (pair_key, episodes) in enumerate(sorted(rewards_by_pair.items())):
        sorted_episodes = sorted(episodes.items())
        ep_nums = [ep for ep, _ in sorted_episodes]
        rewards = [r for _, r in sorted_episodes]

        # Shorten pair key for legend
        short_key = f"Pair {i+1}"
        ax1.plot(ep_nums, rewards, marker='o', label=short_key, linewidth=2, markersize=6)

    ax1.set_xlabel("Episode", fontsize=12)
    ax1.set_ylabel("Average Total Reward", fontsize=12)
    ax1.set_title("Average Reward by Pair Across Episodes", fontsize=14)
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)

    # Plot 2: Action mismatches by pair over episodes
    ax2 = axes[1]
    for i, (pair_key, episodes) in enumerate(sorted(mismatches_by_pair.items())):
        sorted_episodes = sorted(episodes.items())
        ep_nums = [ep for ep, _ in sorted_episodes]
        total_mismatches = [
            m.get("actions.0", 0) + m.get("actions.1", 0) + m.get("row_count_diff", 0)
            for _, m in sorted_episodes
        ]

        short_key = f"Pair {i+1}"
        ax2.bar(
            [ep + i * 0.2 - 0.2 for ep in ep_nums],
            total_mismatches,
            width=0.2,
            label=short_key,
            alpha=0.8
        )

    ax2.set_xlabel("Episode", fontsize=12)
    ax2.set_ylabel("Total Action Mismatches", fontsize=12)
    ax2.set_title("Action Mismatches Between Paired Files by Episode", fontsize=14)
    ax2.legend(loc='best')
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"\nPlot saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Validate and analyze action sequences between paired players in P2P multiplayer games"
    )
    parser.add_argument("data_dir", type=str, nargs="?", help="Path to the scene data directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed mismatch information")
    parser.add_argument("--no-plot", action="store_true", help="Skip generating plots")
    parser.add_argument("--save-plot", type=str, help="Save plot to specified path instead of displaying")
    parser.add_argument(
        "--compare", nargs=2, metavar=("FILE1", "FILE2"),
        help="Compare two specific export files instead of scanning directory"
    )
    args = parser.parse_args()

    # Handle compare mode (Phase 39: VERIFY-01)
    if args.compare:
        file1, file2 = Path(args.compare[0]), Path(args.compare[1])
        if not file1.exists():
            print(f"Error: File not found: {file1}")
            sys.exit(1)
        if not file2.exists():
            print(f"Error: File not found: {file2}")
            sys.exit(1)
        sys.exit(compare_files(file1, file2, args.verbose))

    # Require data_dir for directory scan mode
    if not args.data_dir:
        parser.error("data_dir is required when not using --compare mode")

    data_dir = Path(args.data_dir)

    print(f"Loading data from: {data_dir}")
    print("=" * 70)

    try:
        pairs = load_episode_data(data_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not pairs:
        print("No paired data found!")
        sys.exit(1)

    # Count total files and episodes
    total_files = sum(len(files) for files in pairs.values())
    print(f"Found {len(pairs)} unique pair(s) with {total_files} total files\n")

    # Analyze all pairs
    validation_results, rewards_by_pair, mismatches_by_pair, raw_episode_data = analyze_pairs(pairs, verbose=args.verbose)

    # Print summary for each pair
    all_valid = True
    total_episodes = 0
    valid_episodes = 0

    for pair_key in sorted(pairs.keys()):
        pair_short = f"{pair_key[0][:8]}...{pair_key[1][:8]}"
        print(f"\nPair: {pair_short}")
        print("-" * 50)

        episodes = validation_results.get(pair_key, {})
        rewards = rewards_by_pair.get(pair_key, {})
        mismatches = mismatches_by_pair.get(pair_key, {})

        for ep_num in sorted(episodes.keys()):
            total_episodes += 1
            is_valid, errors = episodes[ep_num]
            reward = rewards.get(ep_num, 0)
            mismatch = mismatches.get(ep_num, {})

            total_action_mismatch = mismatch.get("actions.0", 0) + mismatch.get("actions.1", 0)
            row_diff = mismatch.get("row_count_diff", 0)

            status = "VALID" if is_valid else "INVALID"
            if is_valid:
                valid_episodes += 1
            else:
                all_valid = False

            print(f"  Episode {ep_num:3d}: {status:7s} | Reward: {reward:8.1f} | "
                  f"Action mismatches: {total_action_mismatch:4d} | Row diff: {row_diff:3d}")

            if args.verbose and errors:
                for error in errors:
                    print(f"      - {error}")

    # Overall summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total pairs:    {len(pairs)}")
    print(f"Total episodes: {total_episodes}")
    print(f"Valid episodes: {valid_episodes} ({100*valid_episodes/total_episodes:.1f}%)" if total_episodes > 0 else "Valid episodes: 0")

    # Aggregate stats
    all_rewards = []
    all_mismatches = []
    for pair_rewards in rewards_by_pair.values():
        all_rewards.extend(pair_rewards.values())
    for pair_mismatches in mismatches_by_pair.values():
        for m in pair_mismatches.values():
            all_mismatches.append(m.get("actions.0", 0) + m.get("actions.1", 0))

    if all_rewards:
        print(f"\nReward stats:")
        print(f"  Min:  {min(all_rewards):.1f}")
        print(f"  Max:  {max(all_rewards):.1f}")
        print(f"  Mean: {sum(all_rewards)/len(all_rewards):.1f}")

    if all_mismatches:
        print(f"\nAction mismatch stats:")
        print(f"  Min:  {min(all_mismatches)}")
        print(f"  Max:  {max(all_mismatches)}")
        print(f"  Mean: {sum(all_mismatches)/len(all_mismatches):.1f}")
        print(f"  Episodes with mismatches: {sum(1 for m in all_mismatches if m > 0)}")

    # Generate plots
    if not args.no_plot and (rewards_by_pair or mismatches_by_pair):
        output_path = Path(args.save_plot) if args.save_plot else None
        plot_results(rewards_by_pair, mismatches_by_pair, output_path)

        # Also plot info rewards comparison
        print("\nGenerating info rewards comparison plots...")
        plot_info_rewards_comparison(raw_episode_data, output_path)

    if all_valid:
        print("\nAll action sequences validated successfully!")
        sys.exit(0)
    else:
        print("\nSome episodes have mismatches - see details above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
