import sys
import os
import time
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import daily_uploader
import youtube_api
import download_helpers
import supabase_db

RUN_DURATION = 5.5 * 3600
SLEEP_INTERVAL = 900
DRY_RUN = os.environ.get('INPUT_DRY_RUN', 'false') == 'true'
PROXY_REFRESH_COOLDOWN = 300


def refresh_proxies():
    su_url = os.environ.get('PROXY_SUPABASE_URL', '')
    su_key = os.environ.get('PROXY_SUPABASE_SERVICE_KEY', '')
    if not su_url or not su_key:
        config.log('no proxy database configured — cannot refresh proxies')
        return False
    try:
        import urllib.request
        import urllib.error
        api_url = su_url.rstrip('/') + '/rest/v1/proxy_results?select=ip,port,latency_ms&vplink_ok=eq.true&order=latency_ms.asc&limit=200'
        req = urllib.request.Request(api_url, headers={
            'apikey': su_key,
            'Authorization': 'Bearer ' + su_key,
        })
        proxies = json.loads(urllib.request.urlopen(req, timeout=15).read())
        config.log(f're-fetched {len(proxies)} proxies from database')
        working = []
        for p in proxies:
            p_url = 'http://%s:%s' % (p['ip'], p['port'])
            try:
                t0 = time.time()
                urllib.request.urlopen(
                    urllib.request.Request('http://www.gstatic.com/generate_204'),
                    timeout=5
                )
                lat = int((time.time() - t0) * 1000)
                working.append({'url': p_url, 'latency_ms': lat})
            except Exception:
                pass
            if len(working) >= 10:
                break
        if not working:
            config.log('no working proxies found after refresh')
            return False
        working.sort(key=lambda x: x['latency_ms'])
        proxy_list = [w['url'] for w in working]
        os.environ['WORKING_PROXIES'] = json.dumps(proxy_list)
        os.environ['YT_PROXY'] = proxy_list[0]
        config.log(f'refreshed proxies: {len(proxy_list)} working, best {proxy_list[0]} ({working[0]["latency_ms"]}ms)')
        return True
    except Exception as e:
        config.log(f'proxy refresh failed: {e}')
        return False


def detect_and_queue():
    pid = os.environ.get('PROJECT_ID', '')
    channels = config.load_channels()
    youtube = youtube_api.get_client()
    up_state = daily_uploader.load_upload_state()
    pending_hashes = list(up_state.get('pending_hashes', []))
    processed_hashes = set(up_state.get('processed_hashes', []))
    cursors = supabase_db.get_all_cursors(project_id=pid)
    found_new = False

    for ch_id, ch in channels.items():
        try:
            playlist_id = youtube_api.get_channel_uploads_playlist(youtube, ch_id)
            if not playlist_id:
                continue
            recent = youtube_api.get_recent_videos(youtube, playlist_id, max_results=10)
            recent = youtube_api.filter_long_form_videos(youtube, recent)
            if not recent:
                continue

            cursor = (cursors.get(ch_id) or {}).get('last_video_id', '')
            latest_id = recent[0]['video_id']
            backfill = daily_uploader.get_backfill_count()

            if backfill > 0:
                backfill_new = []
                for v in recent[:backfill]:
                    if v['video_id'] not in processed_hashes and v['video_id'] not in pending_hashes:
                        backfill_new.append(v['video_id'])
                if backfill_new:
                    pending_hashes = backfill_new[::-1] + pending_hashes
                    config.log(f'backfill: queuing {len(backfill_new)} video(s) from {ch_id}: {backfill_new[::-1]}')
                    for vid in backfill_new:
                        supabase_db.add_work_item('detect', project_id=pid,
                            video_id=vid, title='', status='pending')
                    found_new = True

            if cursor:
                new_ids = []
                for v in recent:
                    if v['video_id'] == cursor:
                        break
                    if v['video_id'] not in processed_hashes and v['video_id'] not in pending_hashes:
                        new_ids.append(v['video_id'])
                if new_ids:
                    found_new = True
                    pending_hashes = new_ids[::-1] + pending_hashes
                    config.log(f'{len(new_ids)} new video(s) from {ch.get("name", ch_id)}: {new_ids[::-1]}')
                    for v in recent:
                        if v['video_id'] in new_ids:
                            supabase_db.add_work_item('detect', project_id=pid,
                                video_id=v['video_id'], title=v.get('title', ''), status='pending')
            else:
                config.log(f'first run for {ch_id} — setting baseline cursor to {latest_id}')

            supabase_db.save_channel_cursor(ch_id, {'last_video_id': latest_id}, project_id=pid)

        except Exception as e:
            config.log(f'detect error {ch_id}: {e}')

    up_state['pending_hashes'] = pending_hashes
    daily_uploader.save_upload_state(up_state)
    return found_new


def _find_work_item(pid, video_id):
    items = supabase_db.get_work_queue(project_id=pid, status='pending', limit=20)
    for it in items:
        if it.get('video_id') == video_id:
            return it.get('id')
    return None


def upload_one_pending():
    youtube = youtube_api.get_client()
    pid = os.environ.get('PROJECT_ID', '')
    up_state = daily_uploader.load_upload_state()

    pending_hashes = list(up_state.get('pending_hashes', []))
    processed_hashes = list(up_state.get('processed_hashes', []))

    target_id = None
    temp = list(pending_hashes)
    pending_hashes = []
    for v in temp:
        if v not in processed_hashes and target_id is None:
            target_id = v
        else:
            pending_hashes.append(v)

    if not target_id:
        config.log('nothing pending — all detected videos already uploaded')
        up_state['pending_hashes'] = []
        daily_uploader.save_upload_state(up_state)
        return False

    item_id = _find_work_item(pid, target_id)
    if item_id:
        supabase_db.update_work_item(item_id, status='in_progress')

    can_upload, reason = daily_uploader.can_upload_today()
    if not can_upload:
        config.log(f'cooldown: {reason}')
        up_state['pending_hashes'] = [target_id] + pending_hashes
        daily_uploader.save_upload_state(up_state)
        return False

    config.log(f'processing pending video: {target_id}')
    source_url = f'https://www.youtube.com/watch?v={target_id}'
    vid = {'video_id': target_id, 'title': f'Video {target_id}', 'description': '', 'tags': []}

    try:
        resp = youtube.videos().list(part='snippet', id=target_id).execute()
        items = resp.get('items', [])
        if items:
            sn = items[0]['snippet']
            vid = {
                'video_id': target_id,
                'title': sn.get('title', vid['title']),
                'description': sn.get('description', ''),
                'tags': sn.get('tags', []),
            }
    except Exception as e:
        config.log(f'could not fetch video info: {e}')

    config.log('uploading: ' + vid['title'] + ' (' + target_id + ')')
    result = download_helpers.download_video(source_url, f'/tmp/daily_{target_id}')
    if not result:
        config.log(f'all proxies failed for {target_id} — refreshing proxy pool and retrying...')
        if refresh_proxies():
            result = download_helpers.download_video(source_url, f'/tmp/daily_{target_id}')
        if not result:
            config.log(f'download failed: {target_id} — removing from queue, trying next')
            if item_id:
                supabase_db.update_work_item(item_id, status='failed', error='download failed')
            up_state['pending_hashes'] = pending_hashes
            daily_uploader.save_upload_state(up_state)
            return False

    path = result['path'] if isinstance(result, dict) else result
    config.log(f'processing: {target_id}')
    processed = daily_uploader.process_video(path)
    if not processed:
        config.log(f'processing failed: {target_id}')
        if item_id:
            supabase_db.update_work_item(item_id, status='failed', error='processing failed')
        up_state['pending_hashes'] = [target_id] + pending_hashes
        daily_uploader.save_upload_state(up_state)
        return False

    title = vid.get('title', f'Daily Upload {target_id}')
    desc = vid.get('description', '')
    tags = vid.get('tags', [])

    if DRY_RUN:
        config.log(f'dry run — would upload: {title}')
        processed_hashes.append(target_id)
        up_state['processed_hashes'] = processed_hashes
        up_state['pending_hashes'] = pending_hashes
        daily_uploader.save_upload_state(up_state)
        return True

    can, slot_str, iso_time = daily_uploader.can_upload_today(return_slot=True) if daily_uploader.get_upload_schedule() else (True, None, None)
    publish_at = iso_time if daily_uploader.get_upload_schedule() and can else None
    video_id = daily_uploader.upload_daily(processed, title, desc, tags, source_url=source_url, publish_at=publish_at)
    if video_id:
        config.log(f'uploaded: {video_id}')
        if item_id:
            supabase_db.update_work_item(item_id, status='done')
        processed_hashes.append(target_id)
        up_state['processed_hashes'] = processed_hashes
        up_state['pending_hashes'] = pending_hashes
        daily_uploader.save_upload_state(up_state)
        config.log(f'{len(pending_hashes)} remaining in queue')
        return True
    else:
        config.log(f'upload failed: {title}')
        if item_id:
            supabase_db.update_work_item(item_id, status='failed', error='upload_daily returned None')
        up_state['pending_hashes'] = [target_id] + pending_hashes
        daily_uploader.save_upload_state(up_state)
        return False


def continuous_detect():
    pid = os.environ.get('PROJECT_ID', '')
    start_time = time.time()
    end_time = start_time + RUN_DURATION
    iteration = 0
    total_detected = 0
    total_uploaded = 0

    config.log(f'continuous detect loop started — running for {RUN_DURATION / 3600:.1f}h')

    while time.time() < end_time:
        iteration += 1
        elapsed = (time.time() - start_time) / 3600
        remaining = (end_time - time.time()) / 3600
        config.log(f'\n--- iteration {iteration} ({elapsed:.1f}h elapsed, {remaining:.1f}h remaining) ---')

        try:
            found = detect_and_queue()
            if found:
                total_detected += 1
            config.log(f'detect: {"new videos queued" if found else "nothing new"}')
        except Exception as e:
            config.log(f'detect error: {e}')

        try:
            uploaded = upload_one_pending()
            if uploaded:
                total_uploaded += 1
            config.log(f'upload: {"uploaded for next slot" if uploaded else "no upload (waiting for slot/cooldown or nothing pending)"}')
        except Exception as e:
            config.log(f'upload error: {e}')

        if time.time() >= end_time:
            break

        sleep_time = min(SLEEP_INTERVAL, end_time - time.time())
        if sleep_time > 0:
            config.log(f'sleeping {sleep_time / 60:.0f}min...')
            try:
                time.sleep(sleep_time)
            except KeyboardInterrupt:
                config.log('interrupted')
                break

    config.log(f'\ncontinuous detect loop finished — {iteration} iterations, {total_detected} new, {total_uploaded} uploaded')
    print(f'\nSUMMARY: iterations={iteration} detected={total_detected} uploaded={total_uploaded}')


def main():
    pid = os.environ.get('PROJECT_ID', '')
    run_id = os.environ.get('GITHUB_RUN_ID', f'local-{time.time():.0f}')
    owner = f'{pid}:{run_id}'

    acquired, current_owner = supabase_db.acquire_run_lock(project_id=pid, owner=owner, ttl_hours=6)
    if not acquired:
        config.log(f'another run is active ({current_owner}) — skipping this run to avoid duplicate uploads')
        print(f'SUMMARY: skipped — run already active: {current_owner}')
        return
    config.log(f'run lock acquired: {owner}')

    try:
        continuous_detect()
    finally:
        try:
            supabase_db.release_run_lock(project_id=pid, owner=owner)
            config.log('run lock released')
        except Exception as e:
            config.log(f'lock release failed: {e}')


if __name__ == '__main__':
    main()
