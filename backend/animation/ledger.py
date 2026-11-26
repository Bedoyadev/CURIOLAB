"""What an episode has cost and the stop at the channel's limit. Every paid call goes through
here (check before, add after), so a loop that keeps regenerating cannot spend without end.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from animation.db import Cost, ErrorLog



class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, db: Session, episode_id: int | None, limit_usd: float):
        self._db, self.episode_id, self.limit = db, episode_id, limit_usd

    def spent(self) -> float:
        total = self._db.execute(
            select(func.coalesce(func.sum(Cost.usd), 0.0)).where(Cost.episode_id == self.episode_id)).scalar_one()
        return float(total)

    def check(self, upcoming: float = 0.0) -> None:
        """Refuse before paying, not after."""
        if self.spent() + upcoming > self.limit:
            raise BudgetExceeded(
                f"el episodio lleva {self.spent():.2f} USD y el límite del canal es {self.limit:.2f} USD")

    def add(self, service: str, usd: float, detail: str) -> None:
        self._db.add(Cost(episode_id=self.episode_id, service=service, usd=float(usd), detail=detail))
        self._db.commit()

    def error(self, stage: str, message: str) -> None:
        self._db.add(ErrorLog(episode_id=self.episode_id, stage=stage, message=str(message)[:2000]))
        self._db.commit()
