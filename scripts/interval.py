#!/usr/bin/env python3
"""Agenda da rotina (horários em UTC; Brasília = UTC-3).

Imprime quantos segundos esperar até a próxima rodada, alinhada ao relógio,
ou STOP quando a rotina deve parar. Editar aqui vale a partir da rodada seguinte.
"""
import datetime as dt
import sys

UTC = dt.timezone.utc
# (até quando, intervalo em minutos)
# Encerrada em 4/11 às 10h de Brasília, a pedido: nenhuma rodada automática.
AGENDA = []


def active(now):
    """True se agora está num trecho com atualizações (fora de pausa)."""
    for end, minutes in AGENDA:
        if now < end:
            return minutes is not None
    return False


def next_run(now):
    for end, minutes in AGENDA:
        if now < end:
            if minutes is None:
                return end
            step = minutes * 60
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elapsed = (now - midnight).total_seconds()
            nxt = midnight + dt.timedelta(seconds=(int(elapsed // step) + 1) * step)
            return nxt if nxt < AGENDA[-1][0] else None
    return None


if __name__ == "__main__":
    now = dt.datetime.now(UTC)
    if len(sys.argv) > 1:
        now = dt.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
    nxt = next_run(now) if AGENDA else None
    print("STOP" if nxt is None else max(1, int((nxt - now).total_seconds())))
