import json
from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List

position_limits = {
    "EMERALDS": 80,
    "TOMATOES": 80
}

# EWMA model for TOMATOES: predicted_next_pct_change = K * ewma(pct_change, halflife=HALFLIFE)
TOMATOES_HALFLIFE = 1
TOMATOES_ALPHA = 1 - 0.5 ** (1 / TOMATOES_HALFLIFE)  # 0.5 for halflife=1
TOMATOES_K = -1.13


class Trader:
    def fair_emeralds(self, _state: TradingState, _product_state: dict) -> float:
        return 10000

    def fair_tomatoes(self, state: TradingState, product_state: dict) -> float:
        orderbook = state.order_depths["TOMATOES"]
        bids = orderbook.buy_orders
        asks = orderbook.sell_orders
        if not bids or not asks:
            return product_state.get("prev_mid", 5000)

        mid_price = (max(bids) + min(asks)) / 2
        prev_mid = product_state.get("prev_mid", mid_price)
        prev_ewma = product_state.get("ewma", 0.0)

        pct_change = (mid_price - prev_mid) / prev_mid * 100
        new_ewma = TOMATOES_ALPHA * pct_change + (1 - TOMATOES_ALPHA) * prev_ewma

        # Persist for next tick
        product_state["prev_mid"] = mid_price
        product_state["ewma"] = new_ewma

        pred_pct_change = TOMATOES_K * new_ewma
        return mid_price * (1 + pred_pct_change / 100)

    def quote(self, state: TradingState, product: str, fair: float) -> List[Order]:
        orders = []
        orderbook = state.order_depths[product]
        bids = sorted(orderbook.buy_orders.keys(), reverse=True)
        asks = sorted(orderbook.sell_orders.keys())
        limit = position_limits[product]
        position = state.position.get(product, 0)
        pos = position  # tracks position as orders are added

        if bids and bids[0] > fair:
            for bid in bids:
                if bid <= fair:
                    break
                size_to_fill = min(orderbook.buy_orders[bid], limit + pos)
                if size_to_fill <= 0:
                    break
                pos -= size_to_fill
                orders.append(Order(product, bid, -size_to_fill))

        if asks and asks[0] < fair:
            for ask in asks:
                if ask >= fair:
                    break
                size_to_fill = min(abs(orderbook.sell_orders[ask]), limit - pos)
                if size_to_fill <= 0:
                    break
                pos += size_to_fill
                orders.append(Order(product, ask, size_to_fill))

        remaining_bid = limit - pos
        remaining_ask = limit + pos

        bid_to_penny = max((b for b in bids if b < fair), default=fair - 1)
        ask_to_penny = min((a for a in asks if a > fair), default=fair + 1)

        if bid_to_penny < fair - 1:
            orders.append(Order(product, int(bid_to_penny) + 1, remaining_bid))
        elif bid_to_penny < fair and pos < 0:
            orders.append(Order(product, int(bid_to_penny) + 1, -pos))
        if ask_to_penny > fair + 1:
            orders.append(Order(product, int(ask_to_penny) - 1, -remaining_ask))
        elif ask_to_penny > fair and pos > 0:
            orders.append(Order(product, int(ask_to_penny) - 1, -pos))

        return orders

    def run(self, state: TradingState):
        try:
            trader_state = json.loads(state.traderData) if state.traderData else {}
        except json.JSONDecodeError:
            trader_state = {}

        fair_fns = {
            "EMERALDS": self.fair_emeralds,
            "TOMATOES": self.fair_tomatoes,
        }

        result = {}
        for product, fair_fn in fair_fns.items():
            if product not in state.order_depths:
                continue
            product_state = trader_state.setdefault(product, {})
            fair = fair_fn(state, product_state)
            result[product] = self.quote(state, product, fair)

        return result, 0, json.dumps(trader_state)
