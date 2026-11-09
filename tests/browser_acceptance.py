"""Optional installed-Chromium smoke test, with disposable data root only."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='atlas-ui-') as temp:
    env={**os.environ,'ATLAS_DATA_HOME':str(Path(temp)/'profile'),'ATLAS_PORT':'8766'}
    server=subprocess.Popen([sys.executable,'start_atlas.py'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        from urllib.request import urlopen
        for _ in range(50):
            try:
                with urlopen('http://127.0.0.1:8766/api/v1/bootstrap',timeout=1) as res:
                    if res.status==200:break
            except Exception:time.sleep(.15)
        else:raise RuntimeError('Atlas server failed to start: '+str(server.stderr.read()))
        with sync_playwright() as p:
            system_chromium=Path('/usr/bin/chromium')
            options={'headless':True}
            if system_chromium.exists():options.update(executable_path=str(system_chromium),args=['--no-sandbox'])
            b=p.chromium.launch(**options)
            page=b.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
            errors=[]
            page.on('pageerror',lambda err:errors.append(str(err)))
            page.goto('http://127.0.0.1:8766/',wait_until='networkidle')
            page.get_by_role('button',name='+ New workspace').first.click()
            page.locator('#edit-form input[name="name"]').fill('Backend architecture')
            page.locator('#edit-form input[name="kind_label"]').fill('Engineering')
            page.locator('#edit-form textarea[name="description"]').fill('Build durable local services')
            page.locator('#edit-form button[type="submit"]').click()
            page.get_by_text('Resume checkpoint',exact=True).wait_for(timeout=5000)
            page.get_by_role('button',name='+ Add task').click()
            page.locator('#edit-form input[name="title"]').fill('Prove data boundaries')
            page.locator('#edit-form textarea[name="next_action"]').fill('Write a test for local note safety')
            page.locator('#edit-form button[type="submit"]').click()
            page.get_by_text('Prove data boundaries').wait_for()
            page.get_by_role('button',name='+ New note').click()
            page.locator('#edit-form input[name="title"]').fill('Architecture decisions')
            page.locator('#edit-form textarea[name="content"]').fill('# Architecture\nSQLite is our source of truth.')
            page.locator('#edit-form button[type="submit"]').click()
            page.get_by_text('Architecture decisions').wait_for()
            page.get_by_role('button',name='+ Save checkpoint').click()
            page.locator('#edit-form textarea[name="summary"]').fill('Designed first data ownership boundary')
            page.locator('#edit-form textarea[name="next_action"]').fill('Implement path traversal protection')
            page.locator('#edit-form button[type="submit"]').click()
            page.get_by_text('Implement path traversal protection').wait_for()
            page.reload(wait_until='networkidle')
            page.get_by_text('Implement path traversal protection').wait_for()
            page.screenshot(path=str(ROOT/'docs'/'atlas_v2_m1_preview.png'),full_page=True)
            page.get_by_role('button',name='↗ ChatGPT handoff').click()
            page.get_by_role('button',name='Prepare text').click()
            assert 'Implement path traversal protection' in page.locator('#handoff-text').input_value()
            page.get_by_role('button',name='Close ×').click()
            page.locator('button[data-view="data"]').click()
            page.get_by_role('button',name='Download complete backup').click()
            page.locator('button[data-view="today"]').click()
            page.get_by_text('Prove data boundaries').wait_for()
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(ROOT/'docs'/'atlas_v2_m1_mobile.png'),full_page=True)
            assert not errors,errors
            print('Browser acceptance PASS: create, task, note, checkpoint, restart, handoff, backup, Today, mobile')
            b.close()
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill()
