#!/usr/bin/env python3
"""
Daily Mirror — processes and uploads 1 video per day.

Usage:
  python3 daily_mirror.py process <video_path>    Process a video
  python3 daily_mirror.py upload <video_path>     Process + upload
  python3 daily_mirror.py status                  Show status
  python3 daily_mirror.py warmup                  Start warmup tracker
  python3 daily_mirror.py warmup --reset          Reset warmup from today
  python3 daily_mirror.py test                    Test processing only
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import daily_uploader
import video_processor
import audio_separator
import bgm_manager


def cmd_process(video_path):
    config.log(f"processing: {video_path}")
    result = daily_uploader.process_video(video_path)
    if result:
        config.log(f"output: {result}")
    else:
        config.log("processing failed")
    return result


def cmd_upload(video_path, title=None, description=None, tags=None):
    config.log(f"process + upload: {video_path}")
    video_id, reason = daily_uploader.process_and_upload(
        video_path, title, description, tags
    )
    if video_id:
        config.log(f"uploaded: {video_id}")
    else:
        config.log(f"failed: {reason}")
    return video_id


def cmd_status():
    daily_uploader.start_warmup()
    status = daily_uploader.get_status()
    warmup_total = status['warmup_total']
    warmup_day = status['warmup_day']

    if status['warmup_complete']:
        warmup_str = f"day {warmup_day}/{warmup_total} (COMPLETE)"
    else:
        remaining = warmup_total - warmup_day
        warmup_str = f"day {warmup_day}/{warmup_total} ({remaining} days left)"

    print("\n=== Daily Mirror Status ===")
    print(f"  Warmup:          {warmup_str}")
    print(f"  Can upload:      {'YES' if status['can_upload'] else 'NO'}")
    if not status['can_upload']:
        print(f"  Reason:          {status['upload_reason']}")
    print(f"  Total uploaded:  {status['total_uploaded']}")
    print(f"  Last upload:     {status['last_upload'] or 'never'}")
    print(f"  Processed:       {status['processed_count']} videos")
    print()
    return status


def cmd_warmup(reset=False):
    if reset:
        state = daily_uploader.reset_warmup("manual reset")
        print(f"\nWarmup RESET: {state['warmup_start']}")
    else:
        state = daily_uploader.start_warmup(force=True)
        print(f"\nWarmup started: {state['warmup_start']}")

    day = daily_uploader.get_warmup_day()
    total = daily_uploader._get_warmup_days()
    print(f"Current day: {day}/{total}")
    if day >= total:
        print("Warmup is COMPLETE — uploads enabled")
    else:
        print(f"First upload eligible: {total - day} more days")
    return state


def cmd_test(video_path):
    print("\n=== Testing Processing Pipeline ===")

    print("\n1. Video info...")
    info = video_processor.get_video_info(video_path)
    dur = float(info.get("format", {}).get("duration", 0))
    print(f"   Duration: {dur:.1f}s")

    print("\n2. Applying edits...")
    out1 = f"/tmp/test_edited_{os.path.basename(video_path)}"
    preset = video_processor._random_edit_preset()
    print(f"   Preset: {preset}")
    video_processor.apply_edits(video_path, out1, preset)
    print(f"   Output: {out1}")

    print("\n3. Getting BGM...")
    bgm = bgm_manager.get_bgm_for_duration(dur)
    print(f"   BGM: {bgm}")

    if bgm:
        print("\n4. Trimming BGM...")
        trimmed = bgm_manager.trim_bgm(bgm, dur, "/tmp/test_bgm_trimmed.wav")
        print(f"   Trimmed: {trimmed}")

        print("\n5. Mixing audio...")
        out2 = f"/tmp/test_final_{os.path.basename(video_path)}"
        audio_separator.mix_audio(out1, trimmed, out2)
        print(f"   Final: {out2}")
    else:
        print("\n4. No BGM available, skipping mix")

    print("\n=== Test Complete ===")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "process" and len(sys.argv) >= 3:
        cmd_process(sys.argv[2])
    elif cmd == "upload" and len(sys.argv) >= 3:
        title = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_upload(sys.argv[2], title)
    elif cmd == "status":
        cmd_status()
    elif cmd == "warmup":
        reset = "--reset" in sys.argv
        cmd_warmup(reset=reset)
    elif cmd == "test" and len(sys.argv) >= 3:
        cmd_test(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
