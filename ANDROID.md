# pesa-tracker on Android

The pesa-tracker phone app shows the same dashboard as the website and **detects your
M-Pesa messages by itself**. You don't need a separate forwarding app or to copy any links.

## Install

1. On your phone, open
   <https://github.com/francklinegabs/pesa-tracker/releases/download/android-latest/pesa-tracker.apk>
2. Open the downloaded file. If Android asks, allow installing apps from this source.
   (The app isn't on the Play Store, so this is normal.)

## Set up (once)

1. Open **pesa-tracker** and tap **Allow** when it asks about SMS.
2. Type your pesa-tracker address and tap **Connect**. On a home PC that's the
   "Other devices on this Wi-Fi" address shown in the pesa-tracker window, for example
   `http://192.168.0.102:8765`.
3. Log in, or create an account.

That's it. The app finds your account's link by itself, sends your M-Pesa messages from the
last 90 days once, and from then on records every new M-Pesa SMS automatically.

## Good to know

- Only messages from **MPESA** are ever sent. Your other texts stay on the phone.
- If pesa-tracker can't be reached (PC off, or you're away from home), messages wait on
  the phone and are sent automatically later. Nothing is lost, and nothing is counted twice.
- The **⋮ menu** has: sync status, resend old messages, battery settings, and change server.
- Some phones stop background apps to save battery. If messages arrive late, open
  **⋮ → Battery settings** and set pesa-tracker to **Unrestricted**.
- To update, install the newer APK from the same link. If Android says the app
  "conflicts", uninstall the old one first.
