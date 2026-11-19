"""
Who a finished crew hunt pays, and how much.

Kept apart from the cog that hands the reward over, because the catch-up command has to work
the same share out for a hunt finished before any of this existed. Two readings of one rule
drift within a month; one function cannot.
"""


def split_reward(hunt, claimers: set[int], members: set[int]) -> tuple[dict[int, int], set[int]]:
    """
    `(berries owed by player id, who receives the reward treasure)` for a crew hunt.

    Every member who claimed a stone is paid in full, because gathering the sets is the work,
    and every member of the crew takes a share of the berries on top. `claimers` must already
    hold the member who finished it: finishing is claiming the last stone.
    """
    money = {claimer: hunt.reward_money for claimer in claimers} if hunt.reward_money else {}
    share = hunt.reward_money * hunt.crew_share // 100
    if share:
        for member in members:
            money[member] = money.get(member, 0) + share
    cards: set[int] = set()
    if hunt.reward_ball_id:
        # a claimer who has left the crew since keeps what their stones earned them, and
        # nothing more: they did the work, they are simply no longer aboard
        cards = claimers | members if hunt.crew_reward_ball else claimers
    return {paid: amount for paid, amount in money.items() if amount > 0}, cards
