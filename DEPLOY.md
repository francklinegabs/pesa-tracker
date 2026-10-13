# Run pesa-tracker for everyone and link it to M-Pesa

pesa-tracker is a multi-user web app. Anyone who can open it can **create an account**
with a username and password, and each account's money is kept in its own private
database. Every user can link their own Android phone so their M-Pesa messages are
recorded automatically.

Safaricom has no API for personal M-Pesa accounts (Daraja is only for businesses), so
the link works through the SMS messages that M-Pesa already sends.

There are two ways to run it:

| | Who can reach it | Always on |
|---|---|---|
| **A. On your PC** | People on the same Wi-Fi | Only while the PC is on |
| **B. On PythonAnywhere (free)** | Anyone with internet | Yes |

---

## A. On your PC (same Wi-Fi)

```bash
python -m pesa serve --host 0.0.0.0
```

The window prints two addresses: one for this PC, and one for other devices on the same
Wi-Fi (for example `http://192.168.0.102:8765/`). The first time, Windows asks whether to
allow Python on the network. Choose **Private networks** and click **Allow access**.

- Accounts and data live in `~/.pesa/` (`users.db`, plus one file per user in `users/`).
- **The first account created takes over any data you already had** in `~/.pesa/pesa.db`,
  from before accounts existed. Create your own account first.
- Add `--no-signup` once everyone who should have an account has one.

## B. On PythonAnywhere (free, reachable from anywhere)

1. **Create an account** at <https://www.pythonanywhere.com> on the free *Beginner* plan.
   Your username becomes the address: `https://USERNAME.pythonanywhere.com`.

2. **Get the code.** Open **Consoles → Bash** and run:

   ```bash
   git clone https://github.com/francklinegabs/pesa-tracker.git
   ```

3. **Create the web app.** Go to **Web → Add a new web app → Next → Manual configuration**
   (not Flask or Django), and pick the newest Python version offered (3.10 or later).

4. **Point it at pesa-tracker.** On the Web page, open the **WSGI configuration file** link,
   delete everything in it, and paste this in (replace `USERNAME`):

   ```python
   import os
   import sys

   os.environ["PESA_DATA_DIR"] = "/home/USERNAME/pesa-data"
   # os.environ["PESA_ALLOW_SIGNUP"] = "0"   # uncomment to stop new sign-ups

   sys.path.insert(0, "/home/USERNAME/pesa-tracker")
   from pesa.wsgi import application  # noqa: E402
   ```

5. **Turn on HTTPS.** Under **Security**, switch **Force HTTPS** on.

6. **Reload** with the green button, open `https://USERNAME.pythonanywhere.com`, and
   click **Create an account**.

> **Keep it alive:** free web apps stop after 3 months unless you log in to PythonAnywhere
> and click **"Run until 3 months from today"** on the Web page. They email a reminder first.

**Updating later:** in a Bash console run `cd ~/pesa-tracker && git pull`, then press Reload.

---

## Link your M-Pesa (each user, Android)

1. Log in and open the **Settings** tab. It shows **your personal link**. Copy it.
   On the PC version, open the dashboard **from your phone**, using the Wi-Fi address,
   so the link contains an address your phone can reach.
2. Install **SMS to URL Forwarder** (free, Play Store / F-Droid), or any app that forwards
   SMS to a URL, and allow it to receive SMS.
3. Add a forwarding rule:
   - **Sender:** `MPESA`, so only M-Pesa messages are sent and your other texts stay private.
   - **Method:** POST. **URL:** your personal link.
   - **Body:** the app's default JSON template, which includes `"text": "%text%"`, works.
     pesa-tracker also accepts `message` or `body` fields, a form post, or plain text.
   - Instead of having the token in the URL, you can send it as a header:
     `X-Pesa-Token: <token>` or `Authorization: Bearer <token>`.
4. In Android settings, set the app's battery usage to **Unrestricted**.
5. **Test it:** buy KES 10 of airtime. Within seconds it should appear under **Transactions**.

What gets recorded:

| SMS | Recorded as |
|---|---|
| Paid to a till / buy goods | expense, `shopping` |
| Sent to a person | expense, `transfers` |
| Pay bill ("for account …") | expense, `bills` |
| Airtime | expense, `airtime` |
| Agent withdrawal | expense, `cash` |
| You have received … | income, `income` |
| Transaction cost | separate expense, `fees` |

Categories can be changed afterwards with **Edit**. Each receipt number is stored, so an
SMS sent twice is only recorded once. Older messages, or ones that arrived while the
server was off, can be pasted into the **Paste M-Pesa messages** box on the Transactions page.

---

## Security notes

- Passwords are stored as salted PBKDF2-SHA256 hashes, never as plain text. Wrong
  passwords are slowed down to make guessing impractical.
- The login cookie is HttpOnly, signed with a server key (`secret.key` in the data folder),
  and Secure over HTTPS. It lasts 30 days. Changing your password logs out your other devices.
- Each user's SMS link only writes to that user's account. If a link leaks, use
  **Settings → Make a new link** and update the phone app.
- Every user's data is a separate file in `users/`. Back up the whole data folder now
  and then (on PythonAnywhere: **Files** tab).
- Command-line tools can work on one user's data with `--db`, for example
  `python -m pesa --db ~/.pesa/users/1.db summary`.
