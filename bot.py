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
CONFIG_FILE = "bnbpick_config.json"
CHANNEL = "C4COIN"
console = Console()
logs = []
stop_updater = False

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

def add_log(msg, style="white", account=""):
    now = datetime.now().strftime("%H:%M:%S")
    if account:
        log_msg = f"[bold cyan][{account}][/] [{style}]{msg}[/]"
    else:
        log_msg = f"[{style}]{msg}[/]"
    logs.append(f"[bold grey50]➜ [{now}][/] {log_msg}")
    console.print(f"[bold grey50]➜ [{now}][/] {log_msg}")

def generate_fp(length=16):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

class BNBPickBot:
    def __init__(self, email, password, api_key, account_name=""):
        self.session = requests.Session()
        self.email = email
        self.password = password
        self.api_key = api_key
        self.account_name = account_name if account_name else email.split('@')[0]
        self.domain = "bnbpick.io"
        self.balance = "0.00000000"
        self.level = "Stone"
        self.next_claim = 0
        self.claim_time_remaining = 0
        self.fp = generate_fp()
        self.is_logged_in = False
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

    def solve_captcha(self, action="captcha"):
        try:
            add_log(f"Sending {action} Captcha to Xevil Cloud...", "yellow", self.account_name)
            
            payload = {
                'key': self.api_key,
                'method': 'turnstile',
                'sitekey': '0x4AAAAAAA0_O3uScCqtpqXl',  # BNBPick Turnstile sitekey
                'pageurl': f'https://{self.domain}/faucet.php',
                'json': 1
            }
            
            add_log(f"Sitekey: 0x4AAAAAAA0_O3uScCqtpqXl", "grey", self.account_name)
            
            res = requests.post("https://api.sctg.xyz/in.php", data=payload, timeout=30)
            
            try:
                res_json = res.json()
            except:
                add_log(f"Invalid JSON response: {res.text[:100]}", "red", self.account_name)
                return None
                
            if res_json.get('status') != 1:
                add_log(f"Captcha send failed: {res_json.get('request', 'Unknown error')}", "red", self.account_name)
                return None

            rid = res_json.get('request')
            add_log(f"Captcha ID: {rid}", "grey", self.account_name)
            
            for i in range(40):
                time.sleep(3)
                g = requests.get(
                    f"https://api.sctg.xyz/res.php?key={self.api_key}&action=get&id={rid}&json=1", 
                    timeout=30
                )
                
                try:
                    g_json = g.json()
                except:
                    add_log(f"Invalid JSON response: {g.text[:100]}", "red", self.account_name)
                    continue
                
                status = g_json.get('status')
                request = g_json.get('request', '')
                
                add_log(f"Attempt {i+1}/40: status={status}, request={request[:20] if request else 'None'}", "grey", self.account_name)
                
                if status == 1:
                    add_log(f"✅ Captcha Solved! ({i*3}s)", "green", self.account_name)
                    return request
                elif request == 'ERROR_CAPTCHA_UNSOLVABLE':
                    add_log("❌ Captcha unsolvable", "red", self.account_name)
                    break
                elif request == 'ERROR_NO_SUCH_CAPCHA_ID':
                    add_log("❌ Invalid captcha ID", "red", self.account_name)
                    break
                elif request == 'ERROR_WRONG_USER_KEY':
                    add_log("❌ Wrong API KEY!", "red", self.account_name)
                    break
                elif request == 'ERROR_KEY_DOES_NOT_EXIST':
                    add_log("❌ API KEY does not exist!", "red", self.account_name)
                    break
            
            return None
        except Exception as e:
            add_log(f"Captcha Solver Error: {str(e)}", "red", self.account_name)
            return None

    def login(self):
        try:
            add_log("Connecting to BNBPick Server...", "cyan", self.account_name)
            self.session.cookies.set('fp', self.fp, domain=self.domain)

            try:
                response = self.session.get(
                    f"https://{self.domain}/login.php", 
                    headers={'User-Agent': self.ua}, 
                    timeout=20
                )
                add_log(f"Login page status: {response.status_code}", "grey", self.account_name)
            except Exception as e:
                add_log(f"Initial Connection Error: {str(e)}", "yellow", self.account_name)
                time.sleep(2)
                response = self.session.get(
                    f"https://{self.domain}/login.php", 
                    headers={'User-Agent': self.ua}, 
                    timeout=30
                )

            csrf = self.session.cookies.get('csrf_cookie_name')
            if not csrf:
                add_log("❌ Failed to get CSRF. Try VPN or Check IP.", "red", self.account_name)
                return False, "CSRF Missing"
            
            add_log(f"CSRF Token: {csrf}", "grey", self.account_name)

            token = self.solve_captcha("login")
            if not token:
                add_log("❌ Captcha Failed", "red", self.account_name)
                return False, "Captcha Failed"
            
            add_log(f"Captcha Token: {token[:30]}...", "grey", self.account_name)

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
                'ic-rq': '', 'ic-wid': '', 'ic-cid': '', 'ic-hp': '', 
                'h-captcha-response': '', 'pcaptcha_token': ''
            }

            add_log(f"Login payload: email={self.email}, captcha_type=3", "grey", self.account_name)

            response = self.session.post(
                f"https://{self.domain}/process.php", 
                data=payload, 
                headers=self.headers, 
                timeout=30
            )
            
            add_log(f"Login response: {response.text[:200]}", "grey", self.account_name)
            
            try:
                res = response.json()
            except:
                add_log(f"Invalid JSON: {response.text[:200]}", "red", self.account_name)
                return False, "Invalid JSON response"
            
            if res.get('ret') == 1:
                self.is_logged_in = True
                add_log(f"✅ Login Successful! {res.get('mes', '')}", "green", self.account_name)
                return True, "Success"
            else:
                error_msg = res.get('mes', 'Unknown error')
                add_log(f"❌ Login Failed: {error_msg}", "red", self.account_name)
                return False, error_msg
                
        except requests.exceptions.Timeout:
            add_log("❌ Login Timeout", "red", self.account_name)
            return False, "Timeout"
        except Exception as e:
            add_log(f"❌ Login Error: {str(e)}", "red", self.account_name)
            return False, f"Error: {str(e)}"

    def update_info(self):
        try:
            res = self.session.get(
                f"https://{self.domain}/faucet.php", 
                headers={'User-Agent': self.ua}, 
                timeout=20
            )
            
            bal = re.search(r'user_balance">([\d.]+)', res.text)
            if bal: 
                self.balance = bal.group(1)
            
            lvl = re.search(r'Your level is\s*<b>(.*?)</b>', res.text)
            if lvl: 
                self.level = lvl.group(1)
            
            tmr = re.search(r'show_countdown_clock\((\d+)\)', res.text)
            if tmr:
                self.next_claim = int(tmr.group(1))
                self.claim_time_remaining = self.next_claim
            else:
                self.next_claim = 0
                self.claim_time_remaining = 0
                
            add_log(f"Updated: Balance={self.balance}, Level={self.level}, Next={self.claim_time_remaining}s", "grey", self.account_name)
        except Exception as e:
            add_log(f"Update info error: {str(e)}", "red", self.account_name)

    def claim(self):
        try:
            add_log("Starting Faucet Claim...", "magenta", self.account_name)
            
            token = self.solve_captcha("claim")
            if not token:
                add_log("❌ Claim captcha failed", "red", self.account_name)
                return

            csrf = self.session.cookies.get('csrf_cookie_name')
            if not csrf:
                add_log("❌ No CSRF token for claim", "red", self.account_name)
                return

            ts = int(time.time())
            data_str = f"{random.randint(100,200)}:{random.randint(10,50)}:{ts}"
            xor_key = "6180d2fbdec26dd9399e9f7e4401610575ba7db0dded7d97a5f2efcc7f897491"
            hashed = base64.b64encode(
                "".join(chr(ord(c) ^ ord(xor_key[i % len(xor_key)])) 
                for i, c in enumerate(data_str)).encode()
            ).decode()

            payload = {
                'action': 'claim_hourly_faucet',
                'hash': hashed,
                'captcha_type': '3',
                'c_captcha_response': token,
                'csrf_test_name': csrf
            }

            add_log(f"Claim payload: hash={hashed[:30]}...", "grey", self.account_name)

            res = self.session.post(
                f"https://{self.domain}/process.php", 
                data=payload, 
                headers=self.headers, 
                timeout=30
            )
            
            try:
                res_json = res.json()
            except:
                add_log(f"Invalid JSON: {res.text[:200]}", "red", self.account_name)
                return
            
            if res_json.get('ret') == 1:
                add_log(f"✅ CLAIM SUCCESS: {res_json.get('mes', '')}", "bold green", self.account_name)
                if 'balance' in res_json:
                    self.balance = str(float(res_json['balance']) / 100000000)
            else:
                add_log(f"❌ CLAIM FAILED: {res_json.get('mes', 'Unknown error')}", "bold red", self.account_name)
            
            self.update_info()
            
        except Exception as e:
            add_log(f"Claim Error: {str(e)}", "red", self.account_name)

def account_worker(bot, stop_event):
    while not stop_event.is_set():
        try:
            if bot.claim_time_remaining > 0:
                bot.claim_time_remaining -= 1
            
            if bot.claim_time_remaining <= 0:
                bot.update_info()
                if bot.claim_time_remaining <= 0:
                    bot.claim()
                    bot.update_info()
            
            time.sleep(1)
                
        except Exception as e:
            add_log(f"Worker error: {str(e)}", "red", bot.account_name)
            time.sleep(5)

def build_dashboard(accounts):
    stats_table = Table(show_header=True, header_style="bold white", box=box.ROUNDED, expand=True)
    stats_table.add_column("ACCOUNT", justify="left", style="cyan", ratio=1, no_wrap=True)
    stats_table.add_column("BALANCE (BNB)", justify="center", style="yellow", ratio=1, no_wrap=True)
    stats_table.add_column("NEXT CLAIM IN", justify="center", style="magenta", ratio=1, no_wrap=True)
    stats_table.add_column("LEVEL", justify="center", style="green", ratio=1, no_wrap=True)
    stats_table.add_column("STATUS", justify="center", style="white", ratio=1, no_wrap=True)
    
    for bot in accounts:
        status = "✅ Online" if bot.is_logged_in else "❌ Offline"
        if bot.claim_time_remaining > 0:
            mins, secs = divmod(bot.claim_time_remaining, 60)
            next_claim = f"{mins:02d}:{secs:02d}"
        else:
            next_claim = "00:00"
        
        stats_table.add_row(
            bot.account_name,
            bot.balance,
            next_claim,
            bot.level,
            status
        )
    
    stats_panel = Panel(stats_table, title="[bold white]📊 BNB STATS - MULTI ACCOUNT[/]", border_style="bright_blue")

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

def show_menu(accounts_config):
    clear()
    console.print(Panel.fit(
        "[bold cyan]⚡ BNBPICK MULTI-ACCOUNT BOT ⚡[/]",
        border_style="bright_blue"
    ))
    
    if accounts_config:
        console.print("\n[bold green]📋 Saved Accounts:[/]")
        for i, acc in enumerate(accounts_config, 1):
            console.print(f"  {i}. [cyan]{acc.get('account_name', acc['email'])}[/] - {acc['email']}")
    else:
        console.print("\n[yellow]⚠️ No accounts configured yet![/]")
    
    console.print("\n[bold white]┌─────────────────────────────────────────┐[/]")
    console.print("[bold white]│  [1] ➕ Add New Account                   │[/]")
    console.print("[bold white]│  [2] 🗑️  Remove Account                   │[/]")
    console.print("[bold white]│  [3] 📋 Show All Accounts                │[/]")
    console.print("[bold white]│  [4] 🚀 Start BOT (All Accounts)         │[/]")
    console.print("[bold white]│  [5] 🧹 Clear All Accounts               │[/]")
    console.print("[bold white]│  [6] ❌ Exit                             │[/]")
    console.print("[bold white]└─────────────────────────────────────────┘[/]")
    
    choice = Prompt.ask("[bold yellow]➤ Choose option[/]", choices=["1","2","3","4","5","6"])
    return choice

def add_account(accounts_config, global_api_key):
    clear()
    console.print("[bold cyan]➕ ADD NEW ACCOUNT[/]")
    console.print("[bold grey]────────────────────[/]")
    
    email = Prompt.ask("➤ Account Email")
    password = Prompt.ask("➤ Password", password=True)
    account_name = Prompt.ask("➤ Account Name (optional)", default=email.split('@')[0])
    
    if not global_api_key:
        global_api_key = Prompt.ask("➤ XEVIL API KEY")
    
    accounts_config.append({
        "email": email,
        "password": password,
        "api_key": global_api_key,
        "account_name": account_name
    })
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(accounts_config, f, indent=2)
    
    console.print(f"[green]✅ Account '{account_name}' added successfully![/]")
    time.sleep(1.5)
    return global_api_key

def remove_account(accounts_config):
    if not accounts_config:
        console.print("[red]❌ No accounts to remove![/]")
        time.sleep(1.5)
        return
    
    clear()
    console.print("[bold red]🗑️ REMOVE ACCOUNT[/]")
    console.print("[bold grey]────────────────[/]")
    
    for i, acc in enumerate(accounts_config, 1):
        console.print(f"  {i}. [cyan]{acc.get('account_name', acc['email'])}[/] - {acc['email']}")
    
    choice = Prompt.ask("[bold yellow]➤ Select account number to remove[/]")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(accounts_config):
            removed = accounts_config.pop(idx)
            with open(CONFIG_FILE, "w") as f:
                json.dump(accounts_config, f, indent=2)
            console.print(f"[green]✅ Account '{removed.get('account_name', removed['email'])}' removed![/]")
        else:
            console.print("[red]❌ Invalid number![/]")
    except:
        console.print("[red]❌ Invalid input![/]")
    time.sleep(1.5)

def show_accounts(accounts_config):
    clear()
    console.print("[bold cyan]📋 ALL ACCOUNTS[/]")
    console.print("[bold grey]────────────────[/]")
    
    if not accounts_config:
        console.print("[yellow]⚠️ No accounts configured![/]")
    else:
        for i, acc in enumerate(accounts_config, 1):
            console.print(f"\n[bold white]{i}. Account:[/] [cyan]{acc.get('account_name', acc['email'])}[/]")
            console.print(f"   📧 Email: {acc['email']}")
            console.print(f"   🔑 API Key: {acc.get('api_key', 'Not set')[:10]}...")
    
    Prompt.ask("\n[bold grey]Press Enter to continue[/]")

def clear_accounts(accounts_config):
    if not accounts_config:
        console.print("[yellow]⚠️ No accounts to clear![/]")
        time.sleep(1.5)
        return
    
    confirm = Prompt.ask("[bold red]⚠️ Delete ALL accounts? (y/n)[/]", choices=["y","n"])
    if confirm == "y":
        accounts_config.clear()
        with open(CONFIG_FILE, "w") as f:
            json.dump(accounts_config, f, indent=2)
        console.print("[green]✅ All accounts cleared![/]")
    else:
        console.print("[yellow]❌ Cancelled![/]")
    time.sleep(1.5)

def start_bot(accounts_config):
    if not accounts_config:
        console.print("[red]❌ No accounts to start! Add accounts first.[/]")
        time.sleep(2)
        return False
    
    clear()
    console.print("[bold green]🚀 STARTING BOT...[/]")
    console.print("[bold grey]────────────────[/]")
    time.sleep(1)
    return True

def main():
    global stop_updater
    
    accounts_config = []
    global_api_key = ""
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            if isinstance(config, list):
                accounts_config = config
                if accounts_config:
                    global_api_key = accounts_config[0].get('api_key', '')
            else:
                accounts_config = [config]
                global_api_key = config.get('api_key', '')
    
    while True:
        choice = show_menu(accounts_config)
        
        if choice == "1":
            global_api_key = add_account(accounts_config, global_api_key)
        elif choice == "2":
            remove_account(accounts_config)
        elif choice == "3":
            show_accounts(accounts_config)
        elif choice == "4":
            if start_bot(accounts_config):
                break
        elif choice == "5":
            clear_accounts(accounts_config)
        elif choice == "6":
            console.print("[bold red]❌ Exiting...[/]")
            sys.exit()
    
    if not accounts_config:
        console.print("[red]❌ No accounts configured![/]")
        return
    
    if not global_api_key:
        global_api_key = Prompt.ask("➤ Enter XEVIL API KEY")
        for acc in accounts_config:
            acc['api_key'] = global_api_key
        with open(CONFIG_FILE, "w") as f:
            json.dump(accounts_config, f, indent=2)
    
    bots = []
    threads = []
    stop_event = threading.Event()
    
    for acc in accounts_config:
        api_key = acc.get('api_key', global_api_key)
        if not api_key:
            console.print(f"[red]❌ No API key for {acc.get('account_name', acc['email'])}![/]")
            continue
            
        bot = BNBPickBot(
            acc['email'],
            acc['password'],
            api_key,
            acc.get('account_name', acc['email'].split('@')[0])
        )
        
        success, msg = bot.login()
        if not success:
            add_log(f"Login failed for {bot.account_name}: {msg}", "red")
            continue
        
        bot.update_info()
        bots.append(bot)
        
        thread = Thread(target=account_worker, args=(bot, stop_event))
        thread.daemon = True
        thread.start()
        threads.append(thread)
    
    if not bots:
        console.print("[red]❌ No accounts logged in![/]")
        return
    
    add_log(f"✅ {len(bots)} accounts are running!", "bold green")
    
    old_echo_settings = _disable_echo()
    try:
        with Live(build_dashboard(bots), console=console, refresh_per_second=4, screen=True) as live:
            while True:
                live.update(build_dashboard(bots))
                time.sleep(0.25)
    except KeyboardInterrupt:
        stop_event.set()
        sys.exit()
    finally:
        _restore_echo(old_echo_settings)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_updater = True
        sys.exit()
