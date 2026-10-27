"""Selected PC business responsibilities, executed by existing TLS services.

Root/Host owns activation, legacy drain, consent and the final SDK task route.
This package never invokes an old live plugin and never grants execution.
"""
from .recurrence import advance_due
from .memo_scheduler import NativePCMemoScheduler
from .nonrandom import NativePCNonRandom, weather_observation, weather_change


class NativePCIntegration:
    def __init__(self, memo_notes, reminders, proactive, *, important_dates, authorize,
                 read_weather=None, read_special=None, clock=None, timezone='Asia/Shanghai'):
        self.memos = NativePCMemoScheduler(memo_notes,reminders,authorize=authorize,clock=clock,timezone=timezone)
        self.nonrandom = (NativePCNonRandom(proactive,important_dates,authorize=authorize,
            read_weather=read_weather,read_special=read_special,clock=clock,timezone=timezone) if proactive is not None else None)
        self.active=True

    async def tick(self, scope):
        if not self.active: return dict(state='stopped')
        results={}
        try: results['memos']=await self.memos.tick_memos(scope)
        except PermissionError: results['memos']=dict(state='disabled')
        if self.nonrandom is not None:
            try: results['nonrandom']=await self.nonrandom.tick(scope)
            except PermissionError: results['nonrandom']=dict(state='disabled')
        else: results['nonrandom']=dict(state='disabled',reason='proactive_lane_unavailable')
        return results

    def stop(self):
        self.active=False; self.memos.stop()
        if self.nonrandom is not None: self.nonrandom.stop()

    def diagnostics(self):
        return dict(active=self.active,memos=self.memos.diagnostics(),nonrandom=self.nonrandom.diagnostics() if self.nonrandom is not None else dict(active=False),
            whole_private_companion_replaced=False,owns_shared_services=False)


__all__=['NativePCIntegration','NativePCMemoScheduler','NativePCNonRandom',
         'advance_due','weather_observation','weather_change']
