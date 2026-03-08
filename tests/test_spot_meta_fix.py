"""Tests for pyperliquidity.spot_meta_fix — index→position rewriting."""

from pyperliquidity.spot_meta_fix import fix_spot_meta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spot_meta(
    token_entries: list[dict],
    universe_entries: list[dict],
) -> dict:
    """Build a minimal spotMeta payload."""
    return {"tokens": token_entries, "universe": universe_entries}


# ---------------------------------------------------------------------------
# fix_spot_meta
# ---------------------------------------------------------------------------


class TestFixSpotMetaNoOp:
    """When indices already match positions, the data should pass through unchanged."""

    def test_indices_match_positions(self) -> None:
        """No rewrite needed when token index == array position."""
        tokens = [
            {"name": "USDC", "index": 0, "szDecimals": 2},
            {"name": "PURR", "index": 1, "szDecimals": 0},
        ]
        universe = [
            {"name": "@1", "index": 0, "tokens": [1, 0]},
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        # Should be the same object (no copy needed)
        assert fixed is raw

    def test_empty_universe(self) -> None:
        """Empty universe is a no-op."""
        raw = _make_spot_meta([], [])
        fixed = fix_spot_meta(raw)
        assert fixed is raw

    def test_tokens_without_index_field(self) -> None:
        """Tokens missing 'index' field default to array position → no rewrite."""
        tokens = [
            {"name": "USDC", "szDecimals": 2},
            {"name": "PURR", "szDecimals": 0},
        ]
        universe = [
            {"name": "@1", "index": 0, "tokens": [1, 0]},
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)
        assert fixed is raw


class TestFixSpotMetaRewrite:
    """When indices diverge from positions, universe refs must be rewritten."""

    def test_simple_offset(self) -> None:
        """Token index values offset from array positions get corrected."""
        # Position 0 has index 5, position 1 has index 10
        tokens = [
            {"name": "USDC", "index": 5, "szDecimals": 2},
            {"name": "PURR", "index": 10, "szDecimals": 0},
        ]
        # Universe refs use index values (5, 10), not positions (0, 1)
        universe = [
            {"name": "@1", "index": 0, "tokens": [10, 5]},
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        # After fix, universe tokens should use positions
        assert fixed["universe"][0]["tokens"] == [1, 0]
        # tokens list itself should be unchanged
        assert fixed["tokens"] is raw["tokens"]

    def test_gap_in_indices(self) -> None:
        """Gaps in token indices (e.g. deleted tokens) are handled."""
        tokens = [
            {"name": "USDC", "index": 0, "szDecimals": 2},
            {"name": "PURR", "index": 3, "szDecimals": 0},   # gap: 1,2 missing
            {"name": "HFUN", "index": 7, "szDecimals": 4},   # gap: 4,5,6 missing
        ]
        universe = [
            {"name": "PURR/USDC", "index": 0, "tokens": [3, 0]},
            {"name": "HFUN/USDC", "index": 1, "tokens": [7, 0]},
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        assert fixed["universe"][0]["tokens"] == [1, 0]  # index 3 → pos 1
        assert fixed["universe"][1]["tokens"] == [2, 0]  # index 7 → pos 2

    def test_original_not_mutated(self) -> None:
        """The original data should not be modified in-place."""
        tokens = [
            {"name": "USDC", "index": 5, "szDecimals": 2},
            {"name": "PURR", "index": 10, "szDecimals": 0},
        ]
        universe = [
            {"name": "@1", "index": 0, "tokens": [10, 5]},
        ]
        raw = _make_spot_meta(tokens, universe)
        original_tokens_ref = raw["universe"][0]["tokens"]

        fixed = fix_spot_meta(raw)

        # Original should still have old values
        assert raw["universe"][0]["tokens"] is original_tokens_ref
        assert original_tokens_ref == [10, 5]
        # Fixed should be different
        assert fixed["universe"][0]["tokens"] == [1, 0]

    def test_preserves_other_universe_fields(self) -> None:
        """Non-token fields in universe entries are preserved."""
        tokens = [
            {"name": "USDC", "index": 5, "szDecimals": 2},
            {"name": "PURR", "index": 10, "szDecimals": 0},
        ]
        universe = [
            {"name": "@1", "index": 42, "tokens": [10, 5], "isCanonical": True},
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        entry = fixed["universe"][0]
        assert entry["name"] == "@1"
        assert entry["index"] == 42
        assert entry["isCanonical"] is True
        assert entry["tokens"] == [1, 0]

    def test_realistic_mismatch(self) -> None:
        """Simulates the real-world scenario that caused the IndexError.

        The tokens list has 50 entries (positions 0..49) but some tokens
        carry index values > 49.  Universe entries reference these high
        indices, causing IndexError when used as array subscripts.
        """
        # Simulate: 3 tokens with indices that exceed the array length
        tokens = [
            {"name": "USDC", "index": 0, "szDecimals": 8},
            {"name": "TOKEN_A", "index": 100, "szDecimals": 0},
            {"name": "TOKEN_B", "index": 200, "szDecimals": 4},
        ]
        universe = [
            {"name": "A/USDC", "index": 0, "tokens": [100, 0]},
            {"name": "B/USDC", "index": 1, "tokens": [200, 0]},
        ]
        raw = _make_spot_meta(tokens, universe)

        # Without fix, this would fail:
        # spot_meta["tokens"][100] → IndexError (only 3 entries)
        fixed = fix_spot_meta(raw)

        # After fix, index 100 → position 1, index 200 → position 2
        assert fixed["universe"][0]["tokens"] == [1, 0]
        assert fixed["universe"][1]["tokens"] == [2, 0]

        # Verify the fixed refs actually work as array subscripts
        for entry in fixed["universe"]:
            for token_pos in entry["tokens"]:
                assert token_pos < len(fixed["tokens"])
                # Should not raise
                _ = fixed["tokens"][token_pos]["name"]

    def test_mixed_matching_and_mismatching(self) -> None:
        """Only universe entries with changed tokens are rewritten."""
        tokens = [
            {"name": "USDC", "index": 0, "szDecimals": 2},  # matches
            {"name": "PURR", "index": 5, "szDecimals": 0},  # mismatch
        ]
        universe = [
            {"name": "@1", "index": 0, "tokens": [5, 0]},  # needs rewrite (5→1)
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        assert fixed["universe"][0]["tokens"] == [1, 0]


class TestFixSpotMetaEdgeCases:
    """Edge cases and defensive behavior."""

    def test_unknown_index_preserved(self) -> None:
        """Token refs pointing to unknown indices fall through unchanged."""
        tokens = [
            {"name": "USDC", "index": 5, "szDecimals": 2},
        ]
        # Universe references index 999 which doesn't exist in tokens
        universe = [
            {"name": "@1", "index": 0, "tokens": [999, 5]},
        ]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        # index 999 is not in the map → falls through as 999
        # index 5 → position 0
        assert fixed["universe"][0]["tokens"] == [999, 0]

    def test_single_token(self) -> None:
        """Works with a single token entry."""
        tokens = [{"name": "USDC", "index": 42, "szDecimals": 2}]
        universe = [{"name": "@1", "index": 0, "tokens": [42, 42]}]
        raw = _make_spot_meta(tokens, universe)
        fixed = fix_spot_meta(raw)

        assert fixed["universe"][0]["tokens"] == [0, 0]
