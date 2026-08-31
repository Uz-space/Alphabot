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
from threading import Thread
import threading

# --- [ CONFIGURATION ] ---
CONFIG_FILE = "tronpick_config.json"
CHANNEL = "C4COIN"
console = Console()
logs = []
current_next_claim = "00:00"
stop_updater = False

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
        try:
            res = self.session.get(f"https://{self.domain}/faucet.php", headers={'User-Agent': self.ua}, timeout=20)
            bal = re.search(r'user_balance">([\d.]+)', res.text)
            if bal: self.balance = bal.group(1)
            lvl = re.search(r'Your level is\s*<b>(.*?)</b>', res.text)
            if lvl: self.level = lvl.group(1)
            tmr = re.search(r'show_countdown_clock\((\d+)\)', res.text)
            self.next_claim = int(tmr.group(1)) if tmr else 0
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
    global current_next_claim, stop_updater
    while not stop_updater:
        if bot.next_claim > 0:
            mins, secs = divmod(bot.next_claim, 60)
            current_next_claim = f"{mins:02d}:{secs:02d}"
            bot.next_claim -= 1
        else:
            current_next_claim = "00:00"
        time.sleep(1)

def draw_dashboard(bot):
    clear()
    
    # Sarlavha
    console.print(Align.center("[bold white]╔════════════════════════════════════════╗[/]"))
    console.print(Align.center("[bold white]║           TRONPICK MULTI-BOT PRO       ║[/]"))
    console.print(Align.center("[bold white]╚════════════════════════════════════════╝[/]"))
    console.print()

    # STATS panel - kichik va ixcham
    stats_table = Table(show_header=True, header_style="bold white", box=box.ROUNDED, expand=True)
    stats_table.add_column("ACCOUNT", justify="left", style="cyan")
    stats_table.add_column("BALANCE (TRX)", justify="center", style="yellow")
    stats_table.add_column("NEXT CLAIM IN", justify="center", style="magenta")
    stats_table.add_row(bot.email, bot.balance, current_next_claim)
    console.print(Panel(stats_table, title="[bold white]TRX STATS[/]", border_style="bright_blue"))
    console.print()

    # LOGS panel - 85% kattalikda
    try:
        import shutil
        term_width, term_height = shutil.get_terminal_size()
    except:
        term_width, term_height = 100, 30
    
    # Loglarni ko'rsatish uchun 85% (stats va sarlavhadan keyin qolgan joyning 85%)
    max_lines = int((term_height - 8) * 0.85)  # 85% foiz
    
    # Oxirgi loglarni olish
    log_content = "\n".join(logs[-max_lines:]) if logs else "➜ Initializing..."
    
    # Log panelini 85% kattalikda
    console.print(Panel(
        log_content,
        title="[bold yellow]📋 LIVE LOGS[/]",
        border_style="bright_yellow",
        padding=(0, 1),
        height=max_lines + 2
    ))

def main():
    global stop_updater
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

    # Start timer thread
    stop_updater = False
    timer_thread = Thread(target=update_timer, args=(bot,))
    timer_thread.daemon = True
    timer_thread.start()

    while True:
        bot.update_info()
        draw_dashboard(bot)
        if bot.next_claim <= 0:
            bot.claim()
        else:
            wait_time = bot.next_claim
            with Progress(SpinnerColumn(), TextColumn("[bold cyan]➜ NEXT CLAIM IN:[/] [bold yellow]{task.fields[rem]}"), BarColumn(bar_width=25), console=console, transient=True) as p:
                task = p.add_task("", total=wait_time, rem="")
                while wait_time > 0:
                    mins, secs = divmod(wait_time, 60)
                    p.update(task, advance=1, rem=f"{mins:02d}m {secs:02d}s")
                    time.sleep(1); wait_time -= 1

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_updater = True
        sys.exit()
