"""Print the cron expression for the schedule in config.yaml (runs_per_day spread across run_between)."""
from common import load_config


def cron_from_config(config):
    runs = max(1, int(config.get("runs_per_day", 1)))
    start, end = (h.strip() for h in config.get("run_between", "09:00-17:00").split("-"))
    start_min = int(start[:2]) * 60 + int(start[3:])
    end_min = int(end[:2]) * 60 + int(end[3:])
    step = (end_min - start_min) / runs
    times = [start_min + round(i * step) for i in range(runs)]
    minutes = {t % 60 for t in times}
    days = "1-5" if config.get("weekdays_only", True) else "*"
    if len(minutes) == 1:
        hours = ",".join(str(t // 60) for t in times)
        return f"{minutes.pop()} {hours} * * {days}"
    # Uneven minutes can't share one cron line; round to the hour.
    hours = ",".join(str(round(t / 60)) for t in times)
    return f"0 {hours} * * {days}"


if __name__ == "__main__":
    print(cron_from_config(load_config()))
