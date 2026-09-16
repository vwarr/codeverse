export type ProblemKey =
  | 'Two Sum'
  | 'Reverse Linked List'
  | 'Merge Sorted Arrays'
  | 'Longest Substring Without Repeating Characters'
  | 'Palindrome Check'
  | 'Max Profit from Stock Prices';

export const problemDescriptions: Record<ProblemKey, string> = {
  'Two Sum': `
    Problem: Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target. You may assume that each input would have exactly one solution, and you may not use the same element twice. You can return the answer in any order.

    \n Example 1:
    Input: nums = [2, 7, 11, 15], target = 9
    Output: [0, 1]
    Explanation: The sum of 2 and 7 is 9. Therefore, the indices are [0, 1].

    Example 2:
    Input: nums = [3, 2, 4], target = 6
    Output: [1, 2]
    Explanation: The sum of 2 and 4 is 6. Therefore, the indices are [1, 2].
  `,
  'Reverse Linked List': `
    Problem: Given the head of a singly linked list, reverse the list and return its new head.

    \n Example 1:
    Input: head = [1,2,3,4,5]
    Output: [5,4,3,2,1]
    Explanation: The linked list [1,2,3,4,5] is reversed to [5,4,3,2,1].

    Example 2:
    Input: head = [1,2]
    Output: [2,1]
  `,
  'Merge Sorted Arrays': `
    Problem: Given two sorted arrays, merge them into one sorted array.

    \n Example 1:
    Input: nums1 = [1,2,3], nums2 = [2,5,6]
    Output: [1,2,2,3,5,6]

    Example 2:
    Input: nums1 = [0], nums2 = [1]
    Output: [0,1]
  `,
  'Longest Substring Without Repeating Characters': `
    Problem: Given a string s, find the length of the longest substring without repeating characters.

    \n Example 1:
    Input: s = "abcabcbb"
    Output: 3
    Explanation: The answer is "abc", with length 3.

    Example 2:
    Input: s = "bbbbb"
    Output: 1
    Explanation: The answer is "b", with length 1.
  `,
  'Palindrome Check': `
    Problem: Given an string x, return true if x is a palindrome, and false otherwise.

    \n Example 1:
    Input: x = "racecar"
    Output: true
    Explanation: "racecar" is a palindrome.

    Example 2:
    Input: x = "hello"
    Output: false
    Explanation: "hello" is not a palindrome.
  `,
  'Max Profit from Stock Prices': `
    Problem: You are given an array prices where prices[i] is the price of a given stock on the ith day. Find the maximum profit you can achieve by buying and selling at different days.

    \n Example 1:
    Input: prices = [7,1,5,3,6,4]
    Output: 5
    Explanation: Buy on day 2 (price = 1) and sell on day 5 (price = 6), profit = 6-1 = 5.

    Example 2:
    Input: prices = [7,6,4,3,1]
    Output: 0
    Explanation: In this case, no transactions are done and the max profit = 0.
  `,
};
