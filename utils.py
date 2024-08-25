from collections import defaultdict
from thefuzz import fuzz
import math

def euclidean_distance(box1, box2):
    x1, y1 = (box1[0] + box1[2]) / 2, (box1[1] + box1[3]) / 2
    x2, y2 = (box2[0] + box2[2]) / 2, (box2[1] + box2[3]) / 2
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

def find_closest_word(word_tuple, previous_list):
    min_distance = float('inf')
    closest_word = None
    for candidate_tuple in previous_list:
        distance = euclidean_distance(word_tuple, candidate_tuple)
        if distance < min_distance:
            min_distance = distance
            closest_word = candidate_tuple
    return closest_word

def get_bounding_boxes(words_to_highlight):
    lines = defaultdict(list)
    blocks = defaultdict(list)
    for word in words_to_highlight:
        line_index = word[6]
        blocks[word[5]].append(line_index)
        lines[line_index].append(word)

    line_bounding_boxes = {}
    for line_index, words in lines.items():
        min_x = min(word[0] for word in words)
        min_y = min(word[1] for word in words)
        max_x = max(word[2] for word in words)
        max_y = max(word[3] for word in words)
        line_bounding_boxes[line_index] = (min_x, min_y, max_x, max_y)

    return line_bounding_boxes

def get_closest_words(lists_of_tuples):
    # Remove empty lists in case they exist
    lists_of_tuples = [lst for lst in lists_of_tuples if lst]

    # If no lists, return an empty list
    if not lists_of_tuples:
        return []
    
    # Sort lists by length in descending order
    lists_of_tuples.sort(key=len, reverse=True)

    # Start with the longest list
    result = lists_of_tuples[0]

    # Iterate over the words in the result
    for i in range(1, len(lists_of_tuples)):
        previous_list = lists_of_tuples[i]
        new_result = []
        for word_tuple in result:
            closest_word = find_closest_word(word_tuple, previous_list)
            if closest_word:
                new_result.append(closest_word)
        result = new_result
    
    return result

def find_words_to_highlight(sentence, word_tuples, grace_period_counter):

    sentence_words = sentence.split(" ")

    # List to store words to highlight
    words_to_highlight = []

    init_grace_period_counter = grace_period_counter

    # Pointer to the current word in the sentence
    sentence_pointer = 0

    max_word_distance = 15
    words_passed = 0
    in_matching = False

    # Iterator for word tuples
    i = 0
    while i < len(word_tuples):
        word_in_tuple = word_tuples[i][4]  # The word is at index 4
        
        # Check if the word ends with a hyphen
        if (word_in_tuple.endswith('-') or word_in_tuple.endswith('—')) and (i + 1) < len(word_tuples):
            # Get the next word and concatenate
            next_word_in_tuple = word_tuples[i + 1][4]

            concatenated_word = word_in_tuple[:-1] + next_word_in_tuple  # Remove the hyphen before concatenating

            # Check if the concatenated word matches the current word in the sentence
            if sentence_pointer < len(sentence_words) and fuzz.token_sort_ratio(concatenated_word, sentence_words[sentence_pointer]) >= 80:
                # Add both parts to the highlight list
                in_matching = True
                words_to_highlight.append(word_tuples[i])
                words_to_highlight.append(word_tuples[i + 1])
                sentence_pointer += 1  # Move to the next word in the sentence
                i += 1  # Skip the next tuple since it was already used
                
            else:

                words_passed += 1

                if (in_matching and words_passed > max_word_distance) or (grace_period_counter > 0):
                    sentence_pointer = 0
                    grace_period_counter = init_grace_period_counter  # Reset the grace period
                    words_to_highlight = []
                    
                    in_matching = False
                    words_passed = 0

        elif sentence_pointer < len(sentence_words) and (fuzz.token_sort_ratio(word_in_tuple, sentence_words[sentence_pointer]) >= 80 or fuzz.token_sort_ratio(word_in_tuple, sentence_words[sentence_pointer].replace("-", "", 1)) >= 80):
            # If no hyphenation, match the word as usual
            in_matching = True

            words_to_highlight.append(word_tuples[i])
            sentence_pointer += 1  # Move to the next word in the sentence

            # Decrement grace period counter if it's still active
            if grace_period_counter > 0:
                grace_period_counter -= 1
        else:
            
            words_passed += 1

            if (in_matching and words_passed > max_word_distance) or (grace_period_counter > 0):
                sentence_pointer = 0
                grace_period_counter = init_grace_period_counter  # Reset the grace period
                words_to_highlight = []

                in_matching = False
                words_passed = 0

        # If we've matched the entire sentence, break out of the loop
        if sentence_pointer == len(sentence_words):
            break
        
        i += 1
    
    return words_to_highlight

def find_words_to_highlight_v2(sentence, word_tuples):
    grace_periods = range(2,5)
    all_results = []

    for grace in grace_periods:
        result = find_words_to_highlight(sentence, word_tuples, grace_period_counter=grace)
        all_results.append(result)

    return get_closest_words(all_results)

