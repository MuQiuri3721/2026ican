"""限时追窗:带图真实调用成功立即跑 vlm_note_live(UI 级真实验证)。"""
import os, subprocess, sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
for line in open('.env', encoding='utf-8'):
    if line.startswith('FIRE_VLM_API_KEY='):
        os.environ.setdefault('FIRE_VLM_API_KEY', line.split('=', 1)[1].strip())
from backend.app.vlm import vlm_analyze_images

DEADLINE = time.time() + 35 * 60
attempt = 0
while time.time() < DEADLINE:
    attempt += 1
    result = vlm_analyze_images(['e2e/fire.jpg'],
                                observation={'detections': [], 'mode': 'missing', 'source': 'missing'},
                                environment={}, people_status='unknown',
                                task_id='window-watch', round_index=1)
    if result:
        print(f'[watch] 尝试 {attempt}: 带图真实调用成功! 触发 UI 级验证', flush=True)
        rc = subprocess.run([sys.executable, 'e2e/vlm_note_live.py']).returncode
        print(f'[watch] vlm_note_live 退出码 {rc}', flush=True)
        sys.exit(0 if rc == 0 else 1)
    print(f'[watch] 尝试 {attempt}: 仍限流 {time.strftime("%H:%M:%S")}', flush=True)
    time.sleep(75)
print('[watch] 35 分钟窗口内未等到可用窗口', flush=True)
sys.exit(2)
