# Chapter 2: Binary search

*Sample chapter written for this demo.*

Binary search finds a value in a sorted list by halving the part of the list that can still hold it. Start with two marks, low at the first index and high at the last. Look at the middle item. If it is the value, you are done. If the value is smaller, move high to just before the middle; if it is larger, move low to just after it. Stop when low passes high: the value is not in the list. Each step throws away half of what is left, so a list of 1,000,000 items needs at most 20 looks, where reading every item could take 1,000,000. The list must be sorted first, and sorting costs more than one search, so binary search pays off when you search the same list many times. The most common bug is an off-by-one error in the marks, which makes the loop run forever or skip the last item.
