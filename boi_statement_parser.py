from pathlib import Path
import sys
import pdfplumber
import pandas as pd
import numpy as np



HEADER_MAP = {
    "Date": "date",
    "Transaction details": "details",
    "Payments - out": "out",
    "Payments - in": "in",
    "Balance": "balance"
}

HEADERS = HEADER_MAP.keys()


def get_working_dir():
    if getattr(sys, 'frozen', False):
        # Running as packaged app
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent
    

def find_header_line(page):
    words = page.extract_words(use_text_flow=True)

    lines = {}
    for w in words:
        y = round(w["top"], 1)
        lines.setdefault(y, []).append(w)

    for y, line in lines.items():
        line_text = " ".join(w["text"] for w in line)
        if all(h in line_text for h in HEADERS):
            return line

    raise ValueError("Header line not found")


def build_header_blocks(line_words):
    line_words.sort(key=lambda w: w["x0"])
    blocks = []

    for header in HEADERS:
        parts = header.split()

        for i in range(len(line_words)):
            candidate = line_words[i:i+len(parts)]
            if [w["text"] for w in candidate] == parts:
                blocks.append({
                    "name": header,
                    "x0": candidate[0]["x0"],
                    "x1": candidate[-1]["x1"],
                    "top": candidate[0]["top"]
                })
                break
        else:
            raise ValueError(f"Header not found: {header}")

    return blocks


def build_columns(blocks, page_width):
    blocks.sort(key=lambda b: b["x0"])

    # compute midpoints between headers
    boundaries = []
    for i in range(len(blocks) - 1):
        right = blocks[i]["x1"]
        left = blocks[i+1]["x0"]
        midpoint = (right + left) / 2
        if i < 3:
            boundaries.append(left)
        else:
            boundaries.append(midpoint)

    # final boundaries: page edges + midpoints
    xs = [0] + boundaries + [page_width]

    columns = []
    for i, b in enumerate(blocks):
        columns.append((b["name"], xs[i], xs[i+1]))

    return columns

def extract_rows(page, columns, header_top, subtotal_top):
    words = page.extract_words(use_text_flow=True)

    data = [w for w in words if w["top"] > header_top + 5 and w["top"] < subtotal_top]
    data.sort(key=lambda w: w["top"])

    lines = []
    current = []
    last_y = None

    for w in data:
        if last_y is None or abs(w["top"] - last_y) < 3:
            current.append(w)
        else:
            lines.append(current)
            current = [w]
        last_y = w["top"]

    if current:
        lines.append(current)

    rows = []

    for line in lines:
        row = {c[0]: "" for c in columns}

        for w in line:
            for name, x0, x1 in columns:
                if x0 <= w["x0"] < x1:
                    row[name] += w["text"] + " "

        row = {k: v.strip() for k, v in row.items()}
        if any(row.values()):
            rows.append(row)

    return rows


def is_statement_page(page):
    lines = page.extract_text_lines()

    for line in lines:
        # print(line["text"])
        n_headers = 0
        for header in HEADERS:
            if header in line["text"]:
                n_headers +=1
        
        if n_headers == len(HEADERS):
            print("Headers found")
            return True
        
    return False


def find_table_bounds(page, header_top):
    words = page.extract_words(use_text_flow=True)

    # only look below header
    data = [w for w in words if w["top"] > header_top + 5]

    # group into lines
    lines = {}
    for w in data:
        y = round(w["top"], 1)
        lines.setdefault(y, []).append(w)

    sorted_ys = sorted(lines)

    # heuristic: table rows have similar height spacing
    spacings = [sorted_ys[i+1] - sorted_ys[i] for i in range(len(sorted_ys)-1)]
    median_spacing = sorted(spacings)[len(spacings)//2]

    for i in range(len(spacings)):
        if spacings[i] > median_spacing * 2:
            return sorted_ys[i]

    return page.height - 10  # fallback


def extract_transactions(page):
    if not is_statement_page(page):
        return []

    header_line = find_header_line(page)
    header_blocks = build_header_blocks(header_line)
    columns = build_columns(header_blocks, page.width)

    table_bottom = find_table_bounds(page, header_blocks[0]["top"])

    return extract_rows(
        page,
        columns,
        header_blocks[0]["top"],
        table_bottom
    )


def calculate_balance(df):
    # Convert columns to NumPy arrays for speed
    c_balance = df['balance'].to_numpy(dtype=float)
    c_in = df['in'].to_numpy(dtype=float)
    c_out = df['out'].to_numpy(dtype=float)

    # Loop over indices (NumPy-level, very fast)
    for i in range(1, len(c_balance)):
        if np.isnan(c_balance[i]):
            c_balance[i] = c_balance[i-1] + c_in[i] - c_out[i]

    # Assign back to DataFrame
    return c_balance.round(2)


def clean_transactions(transaction_list):
    # Guard against empty transaction list
    if not transaction_list:
        return pd.DataFrame(columns=['date', 'details', 'out', 'in', 'balance'])

    df = pd.DataFrame(transaction_list)
    df.rename(columns=HEADER_MAP, inplace=True)
    # Clean dates
    df["date"] = pd.to_datetime(df['date'], format='%d %b %Y').dt.strftime('%Y-%m-%d')
    df["date"] = df["date"].ffill()
    # Set empty payments to 0
    processing_cols = ["out", "in"]
    df[processing_cols] = df[processing_cols].replace('', pd.NA).fillna(0)
    # Convert to numeric
    processing_cols.append("balance")
    df[processing_cols] = df[processing_cols].replace({',': ''}, regex=True).apply(pd.to_numeric, errors='coerce')

    df["balance"] = calculate_balance(df)

    return df.drop(df[df["details"] == "BALANCE FORWARD"].index)


def process_statement(pdf_path):
    transactions = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Extracting transactions from {pdf_path}")
        for page in pdf.pages:
            #print(page.extract_text()[:100])
            page_transactions = extract_transactions(page)
            print("Found {} transactions...".format(len(page_transactions)))
            transactions += page_transactions

        print(f"Processing {len(transactions)} transactions.")

        # Handle zero transactions
        if not transactions:
            print(f"Warning: {pdf_path.name} yielded zero transactions. Returning empty DataFrame.")
            return pd.DataFrame(columns=['date', 'details', 'out', 'in', 'balance'])

        transactions_df = clean_transactions(transactions)

    return transactions_df


def main():
    folder = get_working_dir()
    pdfs = list(folder.glob("*.pdf"))

    dfs = []

    for pdf in pdfs:
        # Skip redacted or unlocked PDFs
        if "redacted" in pdf.name.lower() or "_unlocked" in pdf.name.lower():
            print(f"Skipping {pdf.name}")
            continue

        # process pdf
        pdf_df = process_statement(pdf)
        pdf_df["extracted_from"] = pdf.name
        dfs.append(pdf_df)

    # Handle case where no PDFs produced transactions
    if not dfs:
        print("Summary: No PDFs yielded transactions. No output written.")
        sys.exit(1)

    csv_path = folder / "output.csv"

    combined_df = pd.concat(dfs, ignore_index=True)
    combined_df.to_csv(csv_path, index=False)

if __name__ == "__main__":
    main()
