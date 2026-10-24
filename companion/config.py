"""Central configuration for the Fan Companion prototype."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MOCK_DIR = DATA_DIR / "mock"
USERS_DIR = DATA_DIR / "users"


@dataclass(frozen=True)
class LeagueFormat:
    """Liiga regular-season format. Change here if the format differs."""
    name: str = "Liiga"
    direct_spots: int = 6        # 1st-6th go straight to the quarter-finals
    playin_last: int = 10        # 7th-10th play the play-in round
    points_reg_win: int = 3
    points_ot_win: int = 2       # overtime or shootout win
    points_ot_loss: int = 1      # overtime or shootout loss
    home_advantage: float = 1.08


LEAGUE = LeagueFormat()

# "Today" for the demo. Games before this date count as played.
AS_OF = os.getenv("COMPANION_AS_OF", "2026-10-24")
SIMULATIONS = int(os.getenv("COMPANION_SIMULATIONS", "10000"))
