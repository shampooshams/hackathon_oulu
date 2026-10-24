"""Central configuration for the Fan Companion prototype."""
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MOCK_DIR = DATA_DIR / "mock"
MOCK_FOOTBALL_DIR = DATA_DIR / "mock_football"
USERS_DIR = DATA_DIR / "users"


@dataclass(frozen=True)
class LeagueFormat:
    """Rules and wording for one sport's league. Everything sport-specific lives here."""
    sport: str = "hockey"
    name: str = "Liiga"
    direct_spots: int = 4        # Liiga 2026-27: 1st-4th go straight to the quarter-finals
    playin_last: int = 12        # 5th-12th play the first playoff round; 13th and below miss the playoffs
    first_round: str = "first playoff round"
    direct_goal: str = "straight to the quarter-finals"
    reach_goal: str = "make the playoffs"           # what finishing in the top `playin_last` means
    out_label: str = "miss the playoffs"
    points_reg_win: int = 3
    points_ot_win: int = 2       # overtime or shootout win
    points_ot_loss: int = 1      # overtime or shootout loss
    points_draw: int = 0
    draws: bool = False          # football: games can end level after 90 minutes
    tiebreak_reg_wins: bool = True   # Liiga ranks equal points by regulation wins first
    home_advantage: float = 1.08
    periods: int = 3
    period_minutes: int = 20
    period_names: tuple = ("period 1", "period 2", "period 3")
    venue: str = "rink"


# Liiga 2026-27: one-off 17-team season. The official standings agree: playoffsLines after 4th and 12th.
LIIGA = LeagueFormat()

# Football demo: Veikkausliiga-style 12-team league. After the regular season the top 6 play in the
# championship group and the bottom 6 in the relegation group. Demo data only (see generate_mock.py).
VEIKKAUSLIIGA = LeagueFormat(
    sport="football", name="Veikkausliiga", direct_spots=6, playin_last=6, first_round="",
    direct_goal="into the championship group", reach_goal="", out_label="drop into the relegation group",
    points_reg_win=3, points_ot_win=0, points_ot_loss=0, points_draw=1, draws=True, tiebreak_reg_wins=False,
    home_advantage=1.15, periods=2, period_minutes=45, period_names=("1st half", "2nd half"), venue="stadium")

FORMATS = {"liiga": LIIGA, "mock": LIIGA, "football": VEIKKAUSLIIGA}
_current: ContextVar[LeagueFormat] = ContextVar("league", default=LIIGA)


class _ActiveLeague:
    """LEAGUE.<field> reads the format of the sport this request is about.

    Each Streamlit run (and each test) calls use_league() first; the value is per thread/context,
    so two fans looking at different sports at the same time don't mix rules."""
    def __getattr__(self, item):
        return getattr(_current.get(), item)


def use_league(fmt: LeagueFormat) -> None:
    _current.set(fmt)


LEAGUE = _ActiveLeague()

# "Today" for the demo. Games before this date count as played.
AS_OF = os.getenv("COMPANION_AS_OF", "2026-10-24")
SIMULATIONS = int(os.getenv("COMPANION_SIMULATIONS", "10000"))
