from pprint import pprint
from dotenv import load_dotenv

from pykalshi import KalshiClient, OrderStatus


def build_client():
    """
    Build and return a logged-in Kalshi client.

    We are using the same login pattern you already confirmed works.
    """
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")

    client = KalshiClient(demo=False)

    # Simple connectivity check
    status = client.exchange.get_status()
    print("Exchange status:")
    pprint(status)

    return client


def describe_dataframe(name, obj):
    print(f"\n{'=' * 80}")
    print(f"{name}")
    print(f"{'=' * 80}")

    if obj is None:
        print("Object is None")
        return

    if hasattr(obj, "to_dataframe"):
        df = obj.to_dataframe()
        print("Columns:")
        print(list(df.columns))
        print("\nHead:")
        print(df.head())
        print("\nShape:")
        print(df.shape)
    else:
        print("Object does not have to_dataframe().")
        print(type(obj))
        pprint(obj)


def main():
    client = build_client()

    print("\nConnected client type:")
    print(type(client))

    # 1. Positions
    try:
        positions = client.portfolio.get_positions()
        describe_dataframe("POSITIONS", positions)
    except Exception as e:
        print(f"\nError fetching positions: {e}")

    # 2. Open orders
    try:
        orders = client.portfolio.get_orders(status=OrderStatus.RESTING)
        describe_dataframe("OPEN ORDERS", orders)
    except Exception as e:
        print(f"\nError fetching open orders: {e}")

    # 3. Event markets
    series_ticker = "KXINXY"
    event_ticker = "KXINXY-26DEC31H1600"

    try:
        markets = client.get_markets(
            series_ticker=series_ticker,
            event_ticker=event_ticker,
            fetch_all=True,
        )
        describe_dataframe("MARKETS", markets)

        markets_df = markets.to_dataframe()
        if len(markets_df) > 0:
            ticker = markets_df.iloc[0]["ticker"]
            print(f"\nInspecting first market: {ticker}")

            market = client.get_market(ticker)
            orderbook = market.get_orderbook()
            describe_dataframe("ORDERBOOK", orderbook)
    except Exception as e:
        print(f"\nError fetching markets/orderbook: {e}")


if __name__ == "__main__":
    main()