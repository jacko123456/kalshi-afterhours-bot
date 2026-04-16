from dotenv import load_dotenv
from pykalshi import KalshiClient

from kalshi_afterhours_bot.adapters import PykalshiAdapter


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    return KalshiClient(demo=False)


def main():
    client = build_client()
    adapter = PykalshiAdapter(client)

    series_ticker = "KXINXY"
    event_ticker = "KXINXY-26DEC31H1600"
    test_market = "KXINXY-26DEC31H1600-T9000"

    print("\n=== MARKET TICKERS ===")
    tickers = adapter.list_event_market_tickers(
        series_ticker=series_ticker,
        event_ticker=event_ticker,
    )
    print(tickers[:5])
    print(f"Total markets: {len(tickers)}")

    print("\n=== MARKET SNAPSHOT ===")
    snapshot = adapter.get_market_snapshot(test_market)
    print(snapshot)

    print("\n=== MARKET POSITION ===")
    position = adapter.get_market_position(test_market)
    print(position)

    print("\n=== RESTING ORDERS ===")
    resting_orders = adapter.get_resting_orders(test_market)
    for order in resting_orders:
        print(order)


if __name__ == "__main__":
    main()