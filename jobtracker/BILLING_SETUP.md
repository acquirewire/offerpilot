# Accounts, admin & payments — setup

The app now has sign-up / login, plan tiers (free / pro / admin), a free-usage
limit, an **admin panel** (see signups, flip anyone to Pro for free), and Stripe
self-serve upgrades.

## 1. Give yourself admin access (do this first)

Add to your `.env` (repo root):

```ini
ADMIN_EMAIL=you@youremail.com
ADMIN_PASSWORD=a-strong-password
```

Restart the app and **sign up / log in with that exact email** — you'll be admin
automatically (all features free, plus the 🛠️ Admin tab). Everyone else who signs
up starts on Free.

## 2. Turn on payments (Stripe)

1. Create a free account at https://stripe.com and **stay in Test mode** to start
   (toggle top-right of the Stripe dashboard).
2. **Product → Add product** → set a recurring price (e.g. £9 / month). Copy the
   **Price ID** (`price_…`).
3. **Developers → API keys** → copy the **Secret key** (`sk_test_…`).
4. Add to `.env`:
   ```ini
   STRIPE_SECRET_KEY=sk_test_xxx
   STRIPE_PRICE_ID=price_xxx
   APP_URL=https://your-app-url        # where the app is hosted (see step 3)
   ```
5. Restart. Free users now see **“⭐ Upgrade to Pro — £9/mo”** in the sidebar,
   which sends them to Stripe Checkout and flips them to Pro on payment.
6. Test with Stripe's test card `4242 4242 4242 4242`, any future date/CVC.
   When it works in test mode, switch Stripe to **Live** and swap in the
   `sk_live_…` key + live Price ID.

## 3. Host the app (so real users can sign up)

The app must be online — `localhost` is only for you.

- **Streamlit Community Cloud** (free, easiest): push to GitHub, deploy
  `jobtracker/dashboard.py`. Add your `.env` values as **Secrets**.
  ⚠️ Its disk is **ephemeral** — see the database note below.
- **Render / Railway / a VM**: run
  `python -m streamlit run jobtracker/dashboard.py --server.port $PORT`.

### ⚠️ Important: the user database

Accounts are stored in `accounts.db` (SQLite, a local file). On most hosts the
disk resets on every redeploy — which would **wipe your signups**. For a real,
persistent product, move accounts to a hosted database (Postgres, Supabase, or
Turso). The code is isolated in `accounts.py`, so this is a contained change —
ask Claude to migrate it when you're ready to launch for real.

## Before you take real money

You're collecting payments, so you'll want: a **Privacy Policy** and **Terms**,
clarity on **VAT/tax**, and a clear **refund/cancellation** policy. Stripe handles
card security (PCI), but the business/legal side is on you.
