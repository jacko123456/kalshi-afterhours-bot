from pprint import pprint
from dotenv import load_dotenv

from pykalshi import KalshiClient, OrderStatus


def build_client():
    load_dotenv("/Users/jackkeim/Library/Mobile Documents/com~apple~CloudDocs/.envs/kalshi.env")
    client = KalshiClient(demo=False)
    return client


def main():
    client = build_client()

    print("=" * 80)
    print("CLIENT")
    print("=" * 80)
    print(type(client))

    # Inspect a market object
    market_ticker = "KXINXY-26DEC31H1600-T9000"
    market = client.get_market(market_ticker)

    print("\n" + "=" * 80)
    print("MARKET OBJECT")
    print("=" * 80)
    print(type(market))

    market_attrs = [x for x in dir(market) if not x.startswith("_")]
    pprint(market_attrs)

    # Inspect open orders object and first order object if present
    orders = client.portfolio.get_orders(status=OrderStatus.RESTING)
    orders_df = orders.to_dataframe()

    print("\n" + "=" * 80)
    print("ORDERS COLLECTION")
    print("=" * 80)
    print(type(orders))

    order_collection_attrs = [x for x in dir(orders) if not x.startswith("_")]
    pprint(order_collection_attrs)

    if not orders_df.empty:
        first_order_id = orders_df.iloc[0]["order_id"]
        print(f"\nFirst order id from dataframe: {first_order_id}")

        # Try to fetch richer order object if supported
        try:
            order_obj = client.portfolio.get_order(first_order_id)
            print("\n" + "=" * 80)
            print("FIRST ORDER OBJECT")
            print("=" * 80)
            print(type(order_obj))

            order_attrs = [x for x in dir(order_obj) if not x.startswith("_")]
            pprint(order_attrs)
        except Exception as e:
            print(f"\nCould not fetch single order object: {e}")


if __name__ == "__main__":
    main()