import os
import json
import time
import base64
import random
import requests
import re
import sys
import string
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich import box
from rich.align import Align
from rich.live import Live
from rich.console import Group
from threading import Thread
import threading
import shutil
import termios

# --- [ CONFIGURATION ] ---
CONFIG_FILE = "tronpick_config.json"
CHANNEL = "C4COIN"
console = Console()
logs = []
current_next_claim = "00:00"
stop_updater = False
claim_time_remaining = 0  # Yangi o'zgaruvchi - faqat timer uchun

try:
    import termios
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

def _disable_echo():
    if not _HAS_TERMIOS or not sys.stdin.isatty():
        return None
    try:
        old_settings = termios.tcgetattr(sys.stdin)
        new_settings = termios.tcgetattr(sys.stdin)
        new_settings[3] = new_settings[3] & ~termios.ECHO
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, new_settings)
        return old_settings
    except Exception:
        return None

def _restore_echo(old_settings):
    if _HAS_TERMIOS and old_settings is not None:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except Exception:
            pass

def clear():
    os.system('clear' if os.name != 'nt' else 'cls')

def add_log(msg, style="white"):
    now = datetime.now().strftime("%H:%M:%S")
    logs.append(f"[bold grey50]➜ [{now}][/] [{style}]{msg}[/]")
    console.print(f"[bold grey50]➜ [{now}][/] [{style}]{msg}[/]")

def generate_fp(length=16):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

class TronPickBot:
    def __init__(self, email, password, api_key):
        self.session = requests.Session()
        self.email = email
        self.password = password
        self.api_key = api_key
        self.domain = "tronpick.io"
        self.balance = "0.000000"
        self.level = "Stone"
        self.next_claim = 0
        self.fp = generate_fp()
        self.ua = "Mozilla/5.0 (Linux; Android 12; V2029 Build/SP1A.210812.003) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.164 Mobile Safari/537.36"
        self.headers = {
            'User-Agent': self.ua,
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': f'https://{self.domain}',
            'Referer': f'https://{self.domain}/login.php',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }

    def solve_captcha(self):
        try:
            console.print(f"[bold yellow]   ➜ [TRX] Sending Captcha to Xevil Cloud...[/]")
            payload = {
                'key': self.api_key,
                'method': 'turnstile',
                'sitekey': '0x4AAAAAAAW74HiAaujGhyeV',
                'pageurl': f'https://{self.domain}/faucet.php',
                'json': 1
            }
            res = requests.post("https://api.sctg.xyz/in.php", data=payload, timeout=30).json()
            if res.get('status') != 1: return None

            rid = res.get('request')
            for i in range(40):
                console.print(f"[bold yellow]   ➜ [TRX] Waiting for Solver... ({i*3}s)[/]", end="\r")
                time.sleep(3)
                g = requests.get(f"https://api.sctg.xyz/res.php?key={self.api_key}&action=get&id={rid}&json=1", timeout=30).json()
                if g.get('status') == 1:
                    console.print(f"[bold green]   ➜ [TRX] Captcha Solved!                      [/]")
                    return g.get('request')
                if g.get('request') == 'ERROR_CAPTCHA_UNSOLVABLE': break
            return None
        except Exception as e:
            add_log(f"Captcha Solver Error: {str(e)}", "red")
            return None

    def login(self):
        try:
            add_log("Connecting to TronPick Server...", "cyan")
            self.session.cookies.set('fp', self.fp, domain=self.domain)

            try:
                self.session.get(f"https://{self.domain}/login.php", headers={'User-Agent': self.ua}, timeout=20)
            except:
                add_log("Initial Connection Slow, Retrying...", "yellow")
                self.session.get(f"https://{self.domain}/login.php", headers={'User-Agent': self.ua}, timeout=30)

            csrf = self.session.cookies.get('csrf_cookie_name')
            if not csrf:
                add_log("Failed to get CSRF. Try VPN or Check IP.", "red")
                return False, "CSRF Missing"

            token = self.solve_captcha()
            if not token: return False, "Captcha Failed"

            payload = {
                'action': "login",
                'email': self.email,
                'password': self.password,
                'captcha_type': "3",
                'c_captcha_response': token,
                'csrf_test_name': csrf,
                'twofa': '',
                'g-recaptcha-response': '',
                '_iconcaptcha-token': '',
                'ic-rq': '', 'ic-wid': '', 'ic-cid': '', 'ic-hp': '', 'h-captcha-response': '', 'pcaptcha_token': ''
            }

            response = self.session.post(f"https://{self.domain}/process.php", data=payload, headers=self.headers, timeout=30)
            res = response.json()
            if res.get('ret') == 1: return True, "Success"
            return False, res.get('mes')
        except Exception as e:
            return False, f"Network Error: {str(e)}"

    def update_info(self):
        global claim_time_remaining
        try:
            res = self.session.get(f"https://{self.domain}/faucet.php", headers={'User-Agent': self.ua}, timeout=20)
            bal = re.search(r'user_balance">([\d.]+)', res.text)
            if bal: self.balance = bal.group(1)
            lvl = re.search(r'Your level is\s*<b>(.*?)</b>', res.text)
            if lvl: self.level = lvl.group(1)
            tmr = re.search(r'show_countdown_clock\((\d+)\)', res.text)
            if tmr:
                self.next_claim = int(tmr.group(1))
                claim_time_remaining = self.next_claim  # Timerga o'rnatamiz
            else:
                self.next_claim = 0
                claim_time_remaining = 0
        except: pass

    def claim(self):
        try:
            add_log("Starting Faucet Claim...", "magenta")
            token = self.solve_captcha()
            if not token: return

            csrf = self.session.cookies.get('csrf_cookie_name')
            ts = int(time.time())
            data_str = f"{random.randint(100,200)}:{random.randint(10,50)}:{ts}"
            xor_key = "0542f6c18bc7906d742a8401d0b5ef7f50ee304bff4f032348a4ceb3fd2d6bb1"
            hashed = base64.b64encode("".join(chr(ord(c)^ord(xor_key[i%len(xor_key)])) for i,c in enumerate(data_str)).encode()).decode()

            payload = {
                'action': 'claim_hourly_faucet',
                'hash': hashed,
                'captcha_type': '3',
                'c_captcha_response': token,
                'csrf_test_name': csrf
            }

            res = self.session.post(f"https://{self.domain}/process.php", data=payload, headers=self.headers, timeout=30).json()
            if res.get('ret') == 1:
                add_log(f"CLAIM SUCCESS: {res.get('mes')}", "bold green")
            else:
                add_log(f"CLAIM FAILED: {res.get('mes')}", "bold red")
            self.update_info()
        except: add_log("Claim Server Timeout", "red")

def update_timer(bot):
    global current_next_claim, stop_updater, claim_time_remaining
    while not stop_updater:
        if claim_time_remaining > 0:
            mins, secs = divmod(claim_time_remaining, 60)
            current_next_claim = f"{mins:02d}:{secs:02d}"
            claim_time_remaining -= 1
        else:
            current_next_claim = "00:00"
        time.sleep(1)

def build_dashboard(bot):
    """Yangi UI - Live bilan ishlaydi"""
    # STATS panel
    stats_table = Table(show_header=True, header_style="bold white", box=box.ROUNDED, expand=True)
    stats_table.add_column("ACCOUNT", justify="left", style="cyan", ratio=1, no_wrap=True)
    stats_table.add_column("BALANCE (TRX)", justify="center", style="yellow", ratio=1, no_wrap=True)
    stats_table.add_column("NEXT CLAIM IN", justify="center", style="magenta", ratio=1, no_wrap=True)
    stats_table.add_row(bot.email, bot.balance, current_next_claim)
    stats_panel = Panel(stats_table, title="[bold white]TRX STATS[/]", border_style="bright_blue")

    # LOGS panel
    term_height = console.size.height
    max_lines = max(int((term_height - 5) * 0.90), 3)
    log_content = "\n".join(logs[-max_lines:]) if logs else "➜ Initializing..."
    logs_panel = Panel(
        log_content,
        title="[bold yellow]📋 LIVE LOGS[/]",
        border_style="bright_yellow",
        padding=(0, 1),
        height=max_lines + 2
    )

    return Group(stats_panel, logs_panel)

def main():
    global stop_updater, claim_time_remaining
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f: conf = json.load(f)
    else:
        clear()
        conf = {"email": Prompt.ask("➤ TRX Email"), "password": Prompt.ask("➤ TRX Password", password=True), "api_key": Prompt.ask("➤ XEVIL API KEY")}
        with open(CONFIG_FILE, "w") as f: json.dump(conf, f)

    bot = TronPickBot(conf['email'], conf['password'], conf['api_key'])
    success, msg = bot.login()
    if not success:
        console.print(f"[bold red]\n[!] LOGIN FAILED! Reason: {msg}[/]")
        if "Network Error" in msg: console.print("[bold yellow]Tip: Try using a VPN or check your Internet connection.[/]")
        if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
        return

    # Ma'lumotlarni birinchi marta yangilash
    bot.update_info()
    claim_time_remaining = bot.next_claim

    # Start timer thread
    stop_updater = False
    timer_thread = Thread(target=update_timer, args=(bot,))
    timer_thread.daemon = True
    timer_thread.start()

    old_echo_settings = _disable_echo()
    try:
        with Live(build_dashboard(bot), console=console, refresh_per_second=4, screen=True) as live:
            while True:
                # Faqat claim vaqti 0 bo'lganda yangilaymiz
                if claim_time_remaining <= 0:
                    bot.update_info()
                    claim_time_remaining = bot.next_claim
                    if claim_time_remaining <= 0:
                        # Claim qilish vaqti keldi
                        bot.claim()
                        bot.update_info()
                        claim_time_remaining = bot.next_claim
                    live.update(build_dashboard(bot))
                else:
                    live.update(build_dashboard(bot))
                    time.sleep(0.25)
    except KeyboardInterrupt:
        stop_updater = True
        sys.exit()
    finally:
        _restore_echo(old_echo_settings)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_updater = True
        sys.exit()
