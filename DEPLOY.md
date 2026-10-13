# Put pesa-tracker online and link it to M-Pesa

When you're done, pesa-tracker runs all the time at `https://<you>.pythonanywhere.com`,
behind a password. Every M-Pesa confirmation SMS that reaches your Android phone gets
forwarded there and recorded automatically.

Safaricom has no API for personal M-Pesa accounts (Daraja is only for businesses), so
the link works through the SMS messages that M-Pesa already sends you.

Total time: about 20 minutes. Cost: free.

---

## Part 1: host it on PythonAnywhere (free)

1. **Create an account** at <https://www.pythonanywhere.com> and choose the free
   *Beginner* plan. Your username becomes your web address, `https://USERNAME.pythonanywhere.com`.

2. **Get the code.** Open **Consoles → Bash** and run:

   ```bash
   git clone https://github.com/francklinegabs/pesa-tracker.git
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   The second command prints a long random string. That's your **SMS token**, which you'll
   need in step 4 and Part 2. Copy it somewhere safe.

3. **Create the web app.** Go to **Web → Add a new web app → Next → Manual configuration**
   (not Flask or Django), and pick the newest Python version offered (3.10 or later).

4. **Point it at pesa-tracker.** On the Web page, click the **WSGI configuration file**
   link (`/var/www/USERNAME_pythonanywhere_com_wsgi.py`), delete everything in it, and paste
   this in, replacing `USERNAME`, the password and the token:

   ```python
   import os
   import sys

   os.environ["PESA_DB"] = "/home/USERNAME/pesa.db"
   os.environ["PESA_PASSWORD"] = "pick-a-strong-password"
   os.environ["PESA_SMS_TOKEN"] = "the-token-from-step-2"

   sys.path.insert(0, "/home/USERNAME/pesa-tracker")
   from pesa.wsgi import application  # noqa: E402
   ```

   Click **Save**. This file is private to your account. Never commit these values to GitHub.

5. **Turn on HTTPS.** On the Web page, under **Security**, switch **Force HTTPS** on.

6. **Reload** with the green button at the top of the Web page, then open
   `https://USERNAME.pythonanywhere.com`. You should see the login page. Log in with your password.

7. **Set up your accounts** (optional) from the Bash console:

   ```bash
   cd ~/pesa-tracker
   export PESA_DB=~/pesa.db
   python3 -m pesa account add equity --kind bank --opening 18000
   python3 -m pesa budget set food 8000
   python3 -m pesa recurring add expense 14000 rent --day 5 -a equity
   python3 -m pesa goal add laptop 65000 --deadline 2027-04-01
   ```

   Recurring items are added automatically whenever you open the dashboard.

> **Keep it alive:** free web apps sleep after 3 months unless you log in to PythonAnywhere
> and click **"Run until 3 months from today"** on the Web page. They email you a reminder
> beforehand.

**Updating later:** in a Bash console run `cd ~/pesa-tracker && git pull`, then press Reload.

---

## Part 2: forward M-Pesa SMS from your Android phone

Any app that can forward incoming SMS to a URL (a "webhook") works. These steps use
**SMS to URL Forwarder**, which is free and open source (Google Play / F-Droid).
Other forwarders are set up the same way.

1. Install the app and allow it to **receive SMS** when asked.
2. Add a new forwarding rule:
   - **Sender:** `MPESA`, so only M-Pesa messages are forwarded and your other texts stay private.
   - **URL:** `https://USERNAME.pythonanywhere.com/api/sms?token=YOUR_SMS_TOKEN`
   - **Method / body:** POST with JSON. The app's default template, which includes
     `"text": "%text%"`, works as-is. pesa-tracker also accepts a `message` or `body`
     field, a form post, or plain text.
   - If the app lets you add **headers**, you can put the token in a header instead of
     the URL: `X-Pesa-Token: YOUR_SMS_TOKEN` (or `Authorization: Bearer YOUR_SMS_TOKEN`).
3. In Android settings, set the app's battery usage to **Unrestricted** (sometimes
   called "Don't optimise"). Otherwise the phone may stop it in the background.
4. **Test it:** make a small M-Pesa transaction (buy KES 10 of airtime, for example).
   Within a few seconds it should appear under **Transactions** on the dashboard.

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

You can change any category afterwards from the dashboard (**Edit**). Each receipt
number is stored, so if the phone sends the same SMS twice, it's recorded once.

**Older transactions:** paste old M-Pesa messages into the **Paste M-Pesa messages** box
on the Transactions page. Several at once is fine.

---

## Security notes

- The dashboard and its API need your password. The login cookie is HttpOnly, and Secure
  over HTTPS. It lasts 30 days.
- `/api/sms` only accepts requests carrying your SMS token. If the token ever leaks,
  make a new one (Part 1, step 2), update the WSGI file and the phone app, and reload.
- Wrong passwords are slowed down to make guessing impractical. Still, use a password
  you don't use anywhere else.
- Your data is the single file `~/pesa.db`. To back it up, download it from the
  **Files** tab now and then.

## Running at home instead

```bash
PESA_PASSWORD=... PESA_SMS_TOKEN=... python -m pesa serve --host 0.0.0.0
```

This lets the phone reach `http://<your-PC-IP>:8765/api/sms?token=...`, but only while
the PC is on and the phone is on the same Wi-Fi. pesa-tracker refuses to listen beyond
`127.0.0.1` without a password.
