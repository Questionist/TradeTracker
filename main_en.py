import asyncio
import datetime
import uuid
from collections import defaultdict
import psycopg2 as ps
from telebot.async_telebot import AsyncTeleBot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

TOKEN = "YOUR_API_TOKEN"
DB_HOST = "YOUR_DB_HOST"
DB_USER = "YOUR_DB_USER"
DB_NAME = "YOUR_DB_NAME"
DB_PASS = "YOUR_DB_PASS"
SUDOS = (YOUR_SUDOS)

bot = AsyncTeleBot(token=TOKEN)

user_states = defaultdict(dict)


def get_db_connection():
    """
    Establishes and returns a new database connection.

    Returns:
        psycopg2.extensions.connection: A new connection object to the PostgreSQL database.
    """
    return ps.connect(host=DB_HOST, user=DB_USER, database=DB_NAME, password=DB_PASS)


def init_db():
    """
    Initializes the database by creating necessary tables if they do not exist.
    
    Tables created:
    - calcbalances: Stores individual trade details and calculations.
    - calcmessageid: Stores the ID of the last menu message sent to a user for management.
    - balances: Stores daily balance snapshots and references to trades (forIds).

    Raises:
        Exception: Prints error to console if database initialization fails.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS calcbalances(id BIGSERIAL PRIMARY KEY, "day" TIMESTAMP DEFAULT CURRENT_TIMESTAMP, currency TEXT NOT NULL, lots DOUBLE PRECISION DEFAULT NULL, losses DOUBLE PRECISION[] DEFAULT NULL, gains DOUBLE PRECISION[] DEFAULT NULL, entrytarget DOUBLE PRECISION[] DEFAULT NULL, takeprofittarget DOUBLE PRECISION[] DEFAULT NULL, stoploss DOUBLE PRECISION DEFAULT NULL, "type" TEXT DEFAULT NULL, totalbalance DOUBLE PRECISION[] DEFAULT NULL);
            CREATE TABLE IF NOT EXISTS calcmessageid(userid BIGINT NOT NULL, messageid BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS balances(id BIGSERIAL PRIMARY KEY, forIds TEXT[] DEFAULT NULL, balance DOUBLE PRECISION NOT NULL, "day" TEXT NOT NULL, userid BIGINT NOT NULL);
        """
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Init Error: {e}")


init_db()


def calculate_pnl_value(entry, target, lots, trade_type):
    """
    Calculates the Profit and Loss (PnL) value in USD for a given trade.

    Parameters:
        entry (float): The entry price of the asset.
        target (float): The exit price (Take Profit or manual close).
        lots (float): The size of the position in lots.
        trade_type (str): The type of position, 'long' or 'short'.

    Returns:
        float: The calculated PnL value rounded to 2 decimal places. 
               Positive for profit, negative for loss.
    """
    diff = target - entry
    val = diff * lots * 100
    if trade_type.lower() == "short":
        val = -val
    return round(val, 2)


def calculate_balance_percent(balance, pnl):
    """
    Calculates the percentage impact of a PnL value on the total balance.

    Parameters:
        balance (float): The base balance before the trade result.
        pnl (float): The profit or loss amount.

    Returns:
        float: The percentage change. Returns 0.0 if balance is 0.
    """
    if balance == 0:
        return 0.0
    return (pnl / balance) * 100


async def delete_and_save_message_id(user_id, new_message_id):
    """
    Deletes the previous menu message to keep the chat clean and saves the new message ID.

    Parameters:
        user_id (int): The Telegram user ID.
        new_message_id (int): The ID of the newly sent message.

    Database Interactions:
        - Selects old message ID from `calcmessageid`.
        - Deletes that message from Telegram chat.
        - Updates `calcmessageid` with the new ID.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT messageid FROM calcmessageid WHERE userid = %s", (user_id,))
        row = cur.fetchone()
        if row:
            try:
                await bot.delete_message(user_id, row[0])
            except:
                pass
            cur.execute(
                "UPDATE calcmessageid SET messageid = %s WHERE userid = %s",
                (new_message_id, user_id),
            )
        else:
            cur.execute(
                "INSERT INTO calcmessageid(userid, messageid) VALUES(%s, %s)",
                (user_id, new_message_id),
            )
        conn.commit()
        cur.close()
    except:
        pass
    finally:
        conn.close()


def create_keyboard(items, page_number=1, mode="daily", chat_id=0):
    """
    Creates a paginated inline keyboard for lists of items.

    Parameters:
        items (list): A list of tuples containing item data (e.g., id, date).
        page_number (int): The current page number to display (default: 1).
        mode (str): The mode of operation ('daily', 'weekly', 'monthly', 'delete', 'edit').
        chat_id (int): The user's chat ID, required for caching weekly keys in `user_states`.

    Returns:
        telebot.types.InlineKeyboardMarkup: The generated keyboard object.
    """
    PER_PAGE = 10
    start = (page_number - 1) * PER_PAGE
    end = start + PER_PAGE
    current_items = items[start:end]

    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []

    for item in current_items:
        text = ""
        callback = ""
        if mode == "daily":
            text = f"{item[1]}"
            callback = f"id_{item[0]}"
        elif mode == "weekly":
            unique_key = str(uuid.uuid4())[:18]
            if "weekly_map" not in user_states[chat_id]:
                user_states[chat_id]["weekly_map"] = {}
            user_states[chat_id]["weekly_map"][unique_key] = item[0]

            text = f"{item[1]}"
            callback = f"weekly_id_{unique_key}"
        elif mode == "monthly":
            text = str(item[0])
            callback = f"monthly_id_{item[1]}"
        elif mode == "delete":
            date_str = (
                item[1].strftime("%Y-%m-%d")
                if isinstance(item[1], datetime.datetime)
                else str(item[1])
            )
            text = f"{date_str} - {item[0]}"
            callback = f"delete_id_{item[0]}"
        elif mode == "edit":
            date_str = item[1]
            text = f"{date_str} - {item[2]}"
            callback = f"edit_id_{item[0]}"

        buttons.append(InlineKeyboardButton(text, callback_data=callback))

    markup.add(*buttons)

    nav_buttons = []
    if page_number > 1:
        nav_buttons.append(
            InlineKeyboardButton("Previous", callback_data=f"page_{page_number-1}_{mode}")
        )
    nav_buttons.append(InlineKeyboardButton("Close", callback_data="close"))
    if end < len(items):
        nav_buttons.append(
            InlineKeyboardButton("Next", callback_data=f"page_{page_number+1}_{mode}")
        )

    markup.row(*nav_buttons)
    return markup


@bot.callback_query_handler(func=lambda call: call.data.startswith("page_"))
async def handle_pagination(call):
    """
    Handles pagination clicks (Next/Previous buttons).

    Parameters:
        call (telebot.types.CallbackQuery): The callback object.

    Action:
        Parses the page number and mode from `call.data`, fetches the relevant data from DB,
        recreates the keyboard for the new page, and edits the message.
    """
    chat_id = call.message.chat.id
    parts = call.data.split("_")
    page = int(parts[1])
    mode = parts[2]

    conn = get_db_connection()
    items = []
    try:
        cur = conn.cursor()
        if mode == "delete":
            cur.execute("SELECT forIds FROM balances WHERE userid = %s", (chat_id,))
            rows = cur.fetchall()
            all_ids = []
            for r in rows:
                if r[0]:
                    all_ids.extend([int(x) for x in r[0]])
            if all_ids:
                cur.execute(
                    'SELECT id, "day" FROM calcbalances WHERE id = ANY(%s::bigint[])',
                    (all_ids,),
                )
                items = cur.fetchall()
        elif mode == "edit":
            cur.execute(
                'SELECT id, "day", balance FROM balances WHERE userid = %s', (chat_id,)
            )
            items = cur.fetchall()
        elif mode == "daily":
            cur.execute('SELECT id, "day" FROM balances WHERE userid = %s', (chat_id,))
            items = cur.fetchall()
        elif mode == "weekly":
            cur.execute(
                'SELECT id, "day" FROM balances WHERE userid = %s ORDER BY id ASC',
                (chat_id,),
            )
            raw_balances = cur.fetchall()
            weeks = defaultdict(list)
            for bid, day_str in raw_balances:
                dobj = datetime.datetime.strptime(day_str, "%Y-%m-%d").date()
                start_week = dobj - datetime.timedelta(days=(dobj.weekday() + 1) % 7)
                weeks[start_week].append((bid, dobj))
            for start_w, entries in sorted(weeks.items()):
                ids = [e[0] for e in entries]
                min_d = min(e[1] for e in entries)
                max_d = max(e[1] for e in entries)
                items.append((ids, f"{min_d}/{max_d}"))
        elif mode == "monthly":
            cur.execute(
                """
                SELECT DISTINCT TO_CHAR(TO_DATE("day", 'YYYY-MM-DD'), 'Month') AS month_name, 
                EXTRACT(MONTH FROM TO_DATE("day", 'YYYY-MM-DD')) AS month_number
                FROM balances 
                WHERE EXTRACT(YEAR FROM TO_DATE("day", 'YYYY-MM-DD')) = %s AND userid = %s
                ORDER BY month_number
            """,
                (str(datetime.datetime.now().year), chat_id),
            )
            items = cur.fetchall()

        cur.close()
    finally:
        conn.close()

    markup = create_keyboard(items, page, mode, chat_id)
    try:
        await bot.edit_message_reply_markup(
            chat_id, call.message.message_id, reply_markup=markup
        )
    except:
        msg = await bot.send_message(chat_id, f"Page {page}:", reply_markup=markup)
        await delete_and_save_message_id(chat_id, msg.message_id)


@bot.message_handler(commands=["start"])
async def start(message):
    """
    Handles the /start command.

    Parameters:
        message (telebot.types.Message): The message object.

    Action:
        Checks if user is a SUDO (admin). If yes, initializes state and shows the main menu.
    """
    chat_id = message.chat.id
    if chat_id not in SUDOS:
        return await bot.send_message(chat_id, "You do not have access to this bot.")

    if chat_id not in user_states:
        user_states[chat_id] = {}

    buttons = [
        InlineKeyboardButton("New Report", callback_data="newReport"),
        InlineKeyboardButton("Weekly Report", callback_data="weeklyReport"),
        InlineKeyboardButton("Daily Report", callback_data="dailyReport"),
        InlineKeyboardButton("Monthly Report", callback_data="monthlyReport"),
        InlineKeyboardButton("Delete Report", callback_data="deleteReport"),
        InlineKeyboardButton("Edit Balance", callback_data="editBalance"),
        InlineKeyboardButton("Close", callback_data="close"),
    ]
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(*buttons)

    msg = await bot.send_message(
        chat_id, "Please select one of the options below:", reply_markup=markup
    )
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "close")
async def close_handler(call):
    """
    Handles the 'Close' button action.

    Action:
        Deletes user state, removes the menu message, and sends a simple confirmation.
    """
    chat_id = call.message.chat.id
    if chat_id in user_states:
        del user_states[chat_id]
    await bot.delete_message(chat_id, call.message.message_id)
    await bot.send_message(
        chat_id, "Main menu opened /start", reply_markup=ReplyKeyboardRemove()
    )


@bot.callback_query_handler(func=lambda call: call.data == "newReport")
async def new_report(call):
    """
    Initiates the 'New Report' flow.

    Action:
        Sets user state to 'currency' and prompts for input.
    """
    chat_id = call.message.chat.id
    user_states[chat_id] = {"step": "currency", "data": {}}
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Close", callback_data="close")
    )
    msg = await bot.send_message(
        chat_id, "Enter the currency name:", reply_markup=markup
    )
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "dailyReport")
async def daily_report(call):
    """
    Fetches and displays the list of Daily Reports.

    Action:
        Queries `balances` table for user's entries and shows them in a paginated list.
    """
    chat_id = call.message.chat.id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT id, "day" FROM balances WHERE userid = %s', (chat_id,))
        items = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not items:
        return await bot.send_message(chat_id, "No positions found.")

    markup = create_keyboard(items, 1, "daily", chat_id)
    msg = await bot.send_message(
        chat_id, "Select one of the positions below:", reply_markup=markup
    )
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("id_"))
async def daily_chosen(call):
    """
    Displays the details of a specific Daily Report.

    Parameters:
        call (telebot.types.CallbackQuery): Contains the ID of the selected report in `data`.

    Action:
        Fetches detailed trade data (`calcbalances`) linked to the selected day (`balances`)
        and constructs a detailed text summary including PnL, PnL %, and net results.
    """
    chat_id = call.message.chat.id
    b_id = int(call.data.replace("id_", ""))

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT forIds, balance, "day" FROM balances WHERE id = %s AND userid = %s',
            (b_id, chat_id),
        )
        balance_row = cur.fetchone()

        item_text = ""
        if balance_row and balance_row[0]:

            calc_ids = [int(x) for x in balance_row[0]]
            cur.execute(
                "SELECT * FROM calcbalances WHERE id = ANY(%s::bigint[])", (calc_ids,)
            )
            rows = cur.fetchall()

            total_profit_usd = 0.0
            total_loss_usd = 0.0
            gains_pct = []
            losses_pct = []

            item_text = f"*Date: {balance_row[2]}*\nCount: {len(rows)}\n\n"

            for row in rows:

                currency = row[2]
                lots = row[3]
                trade_type = row[9]
                entries = row[6] if row[6] else []
                tps = row[7] if row[7] else []
                sl = row[8]

                row_pnls = []
                for i in range(len(entries)):
                    ent = entries[i]
                    tp = tps[i] if len(tps) > i else 0
                    pnl = calculate_pnl_value(ent, tp, lots, trade_type)
                    row_pnls.append(pnl)
                    if pnl >= 0:
                        total_profit_usd += pnl
                    else:
                        total_loss_usd += abs(pnl)

                pnl_str = ", ".join([f"${x:,.2f}" for x in row_pnls])

                item_text += f"*ID:* {row[0]}\n"
                item_text += f"*Currency:* {currency}\n"
                item_text += f"*Type:* {trade_type}\n"
                item_text += f"*Lots:* {lots}\n"
                item_text += f"*Entries:* {', '.join(map(str, entries))}\n"
                item_text += f"*Targets:* {', '.join(map(str, tps))}\n"
                item_text += f"*Stop Loss:* {sl}\n"
                item_text += f"*PnL ($):* {pnl_str}\n"

                if row[4]:
                    losses_pct.extend(row[4])
                if row[5]:
                    gains_pct.extend(row[5])

                item_text += "\n"

            item_text += f"*Total Net Profit:* ${total_profit_usd:,.2f}\n"
            item_text += f"*Total Net Loss:* ${total_loss_usd:,.2f}\n"
            item_text += f"*Total Profit %:* {sum(gains_pct):.2f}%\n"
            item_text += f"*Total Loss %:* {sum(losses_pct):.2f}%\n"
            item_text += f"*Final Balance:* ${balance_row[1]:,.2f}"

        else:
            item_text = "No information found."

        cur.close()
    finally:
        conn.close()

    if len(item_text) > 4096:
        for x in range(0, len(item_text), 4096):
            await bot.send_message(
                chat_id, item_text[x : x + 4096], parse_mode="Markdown"
            )
    else:
        await bot.send_message(chat_id, item_text, parse_mode="Markdown")
    await start(call.message)


@bot.callback_query_handler(func=lambda call: call.data == "weeklyReport")
async def weekly_report(call):
    """
    Aggregates and displays Weekly Reports.

    Action:
        Fetches all daily balances, groups them by week (starting Monday or based on locale),
        and shows a list of weeks.
    """
    chat_id = call.message.chat.id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT id, "day" FROM balances WHERE userid = %s ORDER BY id ASC',
            (chat_id,),
        )
        raw = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not raw:
        return await bot.send_message(chat_id, "No data found.")

    weeks = defaultdict(list)
    for bid, day_str in raw:
        dobj = datetime.datetime.strptime(day_str, "%Y-%m-%d").date()
        start = dobj - datetime.timedelta(days=(dobj.weekday() + 1) % 7)
        weeks[start].append((bid, dobj))

    items = []
    for s, v in sorted(weeks.items()):
        ids = [x[0] for x in v]
        mn = min(x[1] for x in v)
        mx = max(x[1] for x in v)
        items.append((ids, f"{mn}/{mx}"))

    markup = create_keyboard(items, 1, "weekly", chat_id)
    msg = await bot.send_message(chat_id, "Select Week:", reply_markup=markup)
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("weekly_id_"))
async def weekly_chosen(call):
    """
    Displays the summary for a selected Week.

    Action:
        Retrieved IDs from `user_states` (via cache key), fetches all trades for those days,
        and calculates the total profit/loss for the week.
    """
    chat_id = call.message.chat.id
    unique_key = call.data.replace("weekly_id_", "")

    ids = user_states[chat_id].get("weekly_map", {}).get(unique_key)

    if not ids:
        await bot.send_message(chat_id, "Information expired. Please try again.")
        return await start(call.message)

    conn = get_db_connection()
    text = ""
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT id, "day", balance, forIds FROM balances WHERE id = ANY(%s::bigint[]) AND userid = %s',
            (ids, chat_id),
        )
        bals = cur.fetchall()

        total_profit = 0
        total_loss = 0

        if bals:
            text = f"Weekly Report ({len(bals)} days):\n"
            for b_row in bals:
                if b_row[3]:
                    calc_ids = [int(x) for x in b_row[3]]
                    cur.execute(
                        "SELECT * FROM calcbalances WHERE id = ANY(%s::bigint[])",
                        (calc_ids,),
                    )
                    trades = cur.fetchall()
                    for t in trades:
                        entries = t[6] or []
                        tps = t[7] or []
                        lots = t[3]
                        ttype = t[9]
                        for i in range(len(entries)):
                            tp = tps[i] if i < len(tps) else 0
                            val = calculate_pnl_value(entries[i], tp, lots, ttype)
                            if val >= 0:
                                total_profit += val
                            else:
                                total_loss += abs(val)

            text += f"\nTotal Profit: ${total_profit:,.2f}"
            text += f"\nTotal Loss: ${total_loss:,.2f}"
        else:
            text = "No information available."
        cur.close()
    finally:
        conn.close()

    await bot.send_message(chat_id, text)
    await start(call.message)


@bot.callback_query_handler(func=lambda call: call.data == "monthlyReport")
async def monthly_report(call):
    """
    Aggregates and displays Monthly Reports.

    Action:
        Queries DB for distinct months where data exists and lists them.
    """
    chat_id = call.message.chat.id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT TO_CHAR(TO_DATE("day", 'YYYY-MM-DD'), 'Month') AS month_name, 
            EXTRACT(MONTH FROM TO_DATE("day", 'YYYY-MM-DD')) AS month_number
            FROM balances 
            WHERE EXTRACT(YEAR FROM TO_DATE("day", 'YYYY-MM-DD')) = %s AND userid = %s
            ORDER BY month_number
        """,
            (str(datetime.datetime.now().year), chat_id),
        )
        items = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not items:
        return await bot.send_message(chat_id, "No data available.")

    markup = create_keyboard(items, 1, "monthly", chat_id)
    msg = await bot.send_message(chat_id, "Select Month:", reply_markup=markup)
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("monthly_id_"))
async def monthly_chosen(call):
    """
    Displays the summary for a selected Month.

    Action:
        Fetches all daily records for the chosen month and year, calculates total PnL.
    """
    chat_id = call.message.chat.id
    month_name = call.data.replace("monthly_id_", "")
    m_num = int(float(month_name))
    year = datetime.datetime.now().year

    conn = get_db_connection()
    text = ""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, forIds FROM balances
            WHERE EXTRACT(YEAR FROM TO_DATE("day", 'YYYY-MM-DD')) = %s 
            AND EXTRACT(MONTH FROM TO_DATE("day", 'YYYY-MM-DD')) = %s AND userid = %s
        """,
            (year, m_num, chat_id),
        )
        rows = cur.fetchall()

        prof = 0
        loss = 0
        if rows:
            for r in rows:
                if r[1]:
                    calc_ids = [int(x) for x in r[1]]
                    cur.execute(
                        "SELECT * FROM calcbalances WHERE id = ANY(%s::bigint[])",
                        (calc_ids,),
                    )
                    trades = cur.fetchall()
                    for t in trades:
                        entries = t[6] or []
                        tps = t[7] or []
                        lots = t[3]
                        ttype = t[9]
                        for i in range(len(entries)):
                            tp = tps[i] if i < len(tps) else 0
                            val = calculate_pnl_value(entries[i], tp, lots, ttype)
                            if val >= 0:
                                prof += val
                            else:
                                loss += abs(val)
            text = f"Month {m_num} Report:\nProfit: ${prof:,.2f}\nLoss: ${loss:,.2f}"
        else:
            text = "Empty."
        cur.close()
    finally:
        conn.close()

    await bot.send_message(chat_id, text)
    await start(call.message)


@bot.callback_query_handler(func=lambda call: call.data == "deleteReport")
async def delete_report(call):
    """
    Initiates the Delete Report flow.

    Action:
        Lists all individual trades available for deletion.
    """
    chat_id = call.message.chat.id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT forIds FROM balances WHERE userid = %s", (chat_id,))
        rows = cur.fetchall()
        ids = []
        for r in rows:
            if r[0]:
                ids.extend([int(x) for x in r[0]])

        if not ids:
            items = []
        else:
            cur.execute(
                'SELECT id, "day" FROM calcbalances WHERE id = ANY(%s::bigint[])',
                (ids,),
            )
            items = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not items:
        return await bot.send_message(chat_id, "Nothing to delete.")

    markup = create_keyboard(items, 1, "delete", chat_id)
    msg = await bot.send_message(chat_id, "Select to delete:", reply_markup=markup)
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_id_"))
async def delete_confirm(call):
    """
    Asks for confirmation before deleting a trade.
    """
    chat_id = call.message.chat.id
    tid = call.data.replace("delete_id_", "")
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Yes", callback_data=f"yes_del_{tid}"),
        InlineKeyboardButton("No", callback_data=f"no_del_{tid}"),
    )
    msg = await bot.send_message(
        chat_id,
        f"Are you sure you want to delete position {tid}?",
        reply_markup=markup,
    )
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("yes_del_"))
async def delete_exec(call):
    """
    Executes the deletion of a trade.

    Action:
        Removes the trade from `calcbalances` and updates the array reference in `balances`.
    """
    chat_id = call.message.chat.id
    tid = call.data.replace("yes_del_", "")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM calcbalances WHERE id = %s", (tid,))
        cur.execute(
            "UPDATE balances SET forids = array_remove(forids, %s) WHERE %s = ANY(forids)",
            (str(tid), str(tid)),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    await bot.send_message(chat_id, "Deleted.")
    await start(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith("no_del_"))
async def delete_cancel(call):
    """
    Cancels the deletion via the 'No' button.
    """
    await bot.send_message(call.message.chat.id, "Cancelled.")
    await start(call.message)


@bot.callback_query_handler(func=lambda call: call.data == "editBalance")
async def edit_balance(call):
    """
    Initiates the Edit Balance flow.

    Action:
        Lists available daily balances to edit.
    """
    chat_id = call.message.chat.id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT id, "day", balance FROM balances WHERE userid = %s', (chat_id,)
        )
        items = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not items:
        return await bot.send_message(chat_id, "No balance available.")

    markup = create_keyboard(items, 1, "edit", chat_id)
    msg = await bot.send_message(
        chat_id, "Select to edit:", reply_markup=markup
    )
    await delete_and_save_message_id(chat_id, msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_id_"))
async def edit_balance_chosen(call):
    """
    Prompts the user to enter the new balance value for a selected date.
    """
    chat_id = call.message.chat.id
    bid = int(call.data.replace("edit_id_", ""))
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT "day" FROM balances WHERE id = %s', (bid,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if row:
        user_states[chat_id] = {"step": "edit_val", "day": row[0]}
        await bot.send_message(chat_id, f"Enter new amount for date {row[0]}:")
    else:
        await bot.send_message(chat_id, "Not found.")
        await start(call.message)


@bot.message_handler(func=lambda message: True)
async def message_handler(message):
    """
    Central Message Handler / State Machine.

    Action:
        Intercepts all text messages. Checks `user_states` to see if the user is in a
        specific flow (e.g., 'edit_val' or 'newReport' steps).
        
        Logic:
        - If state is 'edit_val': Update balance in DB.
        - If state is in `flow_steps` (New Report):
            - Validates input.
            - Stores data in `user_states`.
            - Moves to next step.
            - If final step ('sl'): Performs calculation, saves trade to DB, updates balance, and resets state.
    """
    chat_id = message.chat.id
    text = message.text.strip().replace("%", "")

    if chat_id not in user_states:

        return

    curr_state = user_states[chat_id].get("step")
    if not curr_state:
        return

    if curr_state == "edit_val":
        try:
            val = float(text)
            day = user_states[chat_id]["day"]
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    'UPDATE balances SET balance = %s WHERE userid = %s AND "day" = %s',
                    (val, chat_id, day),
                )
                conn.commit()
                cur.close()
            finally:
                conn.close()
            del user_states[chat_id]
            await bot.send_message(chat_id, "Updated.")
            await start(message)
        except ValueError:
            await bot.send_message(chat_id, "Please enter a valid number.")
        return

    flow_steps = [
        "currency",
        "balance",
        "lots",
        "type",
        "entry1",
        "entry2_q",
        "entry2",
        "tp1",
        "tp2_q",
        "tp2",
        "sl",
    ]

    if curr_state in flow_steps:
        data = user_states[chat_id].get("data", {})

        next_step = None

        if curr_state == "currency":
            data["currency"] = text
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    'SELECT id FROM balances WHERE "day" = %s AND userid = %s',
                    (datetime.datetime.now().strftime("%Y-%m-%d"), chat_id),
                )
                if cur.fetchone():
                    next_step = "lots"
                else:
                    next_step = "balance"
                cur.close()
            finally:
                conn.close()

        elif curr_state == "balance":
            try:
                bal = float(text)
                data["balance"] = bal
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        'INSERT INTO balances(balance, "day", userid) VALUES(%s, %s, %s)',
                        (bal, datetime.datetime.now().strftime("%Y-%m-%d"), chat_id),
                    )
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()
                next_step = "lots"
            except:
                await bot.send_message(chat_id, "Enter a number.")
                return

        elif curr_state == "lots":
            try:
                data["lots"] = float(text)
                next_step = "type"
            except:
                await bot.send_message(chat_id, "Enter a number.")
                return

        elif curr_state == "type":
            if text.lower() in ["long", "short"]:
                data["type"] = text.lower()
                next_step = "entry1"
            else:
                await bot.send_message(
                    chat_id,
                    "Please send Long or Short",
                    reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                        "Long", "Short"
                    ),
                )
                return

        elif curr_state == "entry1":
            try:
                data["entry_targets"] = [float(text)]
                next_step = "entry2_q"
            except:
                await bot.send_message(chat_id, "Enter a number.")
                return

        elif curr_state == "entry2_q":
            if text.lower() in ["yes", "y", "بله"]: # Added English support for input logic
                next_step = "entry2"
            else:
                next_step = "tp1"

        elif curr_state == "entry2":
            try:
                data["entry_targets"].append(float(text))
                next_step = "tp1"
            except:
                await bot.send_message(chat_id, "Enter a number.")
                return

        elif curr_state == "tp1":
            try:
                data["tp_targets"] = [float(text)]
                next_step = "tp2_q"
            except:
                await bot.send_message(chat_id, "Enter a number.")
                return

        elif curr_state == "tp2_q":
            if text.lower() in ["yes", "y", "بله"]:
                next_step = "tp2"
            else:
                next_step = "sl"

        elif curr_state == "tp2":
            try:
                data["tp_targets"].append(float(text))
                next_step = "sl"
            except:
                await bot.send_message(chat_id, "Enter a number.")
                return

        elif curr_state == "sl":
            try:
                data["sl"] = float(text)

                conn = get_db_connection()
                try:
                    cur = conn.cursor()

                    entries = data["entry_targets"]
                    tps = data["tp_targets"]
                    lots = data["lots"]
                    ttype = data["type"]

                    profits = []
                    losses = []
                    raw_pnls = []

                    total_pnl = 0

                    for i in range(len(entries)):
                        ent = entries[i]
                        tp = tps[i] if i < len(tps) else tps[-1]
                        val = calculate_pnl_value(ent, tp, lots, ttype)
                        raw_pnls.append(val)
                        total_pnl += val

                        cur.execute(
                            'SELECT balance, id FROM balances WHERE "day" = %s AND userid = %s',
                            (datetime.datetime.now().strftime("%Y-%m-%d"), chat_id),
                        )
                        brow = cur.fetchone()
                        base_balance = brow[0] if brow else 1
                        bal_id = brow[1]

                        pct = calculate_balance_percent(base_balance, val)
                        if val >= 0:
                            profits.append(pct)
                        else:
                            losses.append(pct)

                    cur.execute(
                        """
                        INSERT INTO calcbalances(currency, lots, entrytarget, takeprofittarget, stoploss, type, losses, gains, totalbalance)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                        (
                            data["currency"],
                            lots,
                            entries,
                            tps,
                            data["sl"],
                            ttype,
                            losses,
                            profits,
                            raw_pnls,
                        ),
                    )

                    new_id = cur.fetchone()[0]

                    new_balance = base_balance + total_pnl
                    cur.execute(
                        "UPDATE balances SET balance = %s, forIds = array_append(forIds, %s) WHERE id = %s",
                        (new_balance, str(new_id), bal_id),
                    )

                    conn.commit()
                    cur.close()

                    await bot.send_message(
                        chat_id,
                        f"Saved.\\nPnL: ${total_pnl:,.2f}\\nNew Balance: ${new_balance:,.2f}",
                        reply_markup=ReplyKeyboardRemove(),
                    )

                    del user_states[chat_id]
                    await start(message)
                finally:
                    conn.close()
                return
            except Exception as e:
                print(e)
                await bot.send_message(chat_id, "Error saving.")
                return

        user_states[chat_id]["step"] = next_step

        prompt_map = {
            "lots": "Lots amount:",
            "type": "Position Type (Long/Short):",
            "entry1": "First Entry Target:",
            "entry2_q": "Do you have a second entry? (Yes/No)",
            "entry2": "Second Entry Target:",
            "tp1": "First Take Profit Target:",
            "tp2_q": "Do you have a second target? (Yes/No)",
            "tp2": "Second Take Profit Target:",
            "sl": "Stop Loss:",
        }

        if next_step in prompt_map:
            markup = ReplyKeyboardRemove()
            if next_step == "type":
                markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Long", "Short")
            elif next_step in ["entry2_q", "tp2_q"]:
                markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Yes", "No")

            await bot.send_message(chat_id, prompt_map[next_step], reply_markup=markup)


print("Bot Running...")
try:
    asyncio.run(bot.polling(none_stop=True, timeout=60))
except KeyboardInterrupt:
    exit()
