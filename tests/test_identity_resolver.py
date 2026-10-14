"""Identity resolver: pure match / create / conflict decisions from plain facts."""

from app.services.identity import Conflict, Create, Identity, Match, resolve


def ident(title="Dune", year=2021, content_type="movie", **ids) -> Identity:
    return Identity(title=title, year=year, content_type=content_type, ids=ids)


def test_no_candidates_creates():
    assert resolve(ident(tmdb=1), []) == Create()


def test_same_id_and_kind_matches():
    stored = ident("Other Name", 1999, tmdb=438631)
    assert resolve(ident(tmdb=438631), [stored]) == Match(stored)


def test_same_number_different_kind_is_not_a_match():
    stored = ident("Alpha", 2001, tvdb=100)
    assert resolve(ident("Beta", 2002, tmdb=100), [stored]) == Create()


def test_same_number_different_content_type_is_not_a_match():
    stored = ident("Alpha", 2001, "tv_show", tmdb=5)
    assert resolve(ident("Beta", 2002, "movie", tmdb=5), [stored]) == Create()


def test_imdb_id_matches_across_content_types():
    stored = ident("Alpha", 2001, "tv_show", imdb="tt1")
    assert resolve(ident("Beta", 2002, "movie", imdb="tt1"), [stored]) == Match(stored)


def test_same_title_and_year_matches_without_ids():
    stored = ident("Dune", 2021)
    assert resolve(ident("dune", 2021), [stored]) == Match(stored)


def test_title_match_ignores_accents_and_punctuation():
    stored = ident("Amélie!", 2001)
    assert resolve(ident("Amelie", 2001), [stored]) == Match(stored)


def test_same_title_different_year_creates():
    assert resolve(ident("Dune", 1984), [ident("Dune", 2021)]) == Create()


def test_same_title_different_type_creates():
    assert resolve(ident("Fargo", 1996, "movie"), [ident("Fargo", 1996, "tv_show")]) == Create()


def test_incoming_without_year_matches_by_title():
    stored = ident("Dune", 2021)
    assert resolve(ident("Dune", None), [stored]) == Match(stored)


def test_candidate_without_year_does_not_match_incoming_year():
    assert resolve(ident("Dune", 2021), [ident("Dune", None)]) == Create()


def test_same_title_and_year_but_different_ids_are_distinct_titles():
    stored = ident("Gold", 2016, tmdb=1)
    assert resolve(ident("Gold", 2016, tmdb=2), [stored]) == Create()


def test_title_match_allowed_when_ids_are_of_different_kinds():
    stored = ident("Gold", 2016, tvdb=1)
    assert resolve(ident("Gold", 2016, tmdb=2), [stored]) == Match(stored)


def test_non_latin_titles_match_themselves():
    stored = ident("千と千尋の神隠し", 2001)
    assert resolve(ident("千と千尋の神隠し", 2001), [stored]) == Match(stored)


def test_different_non_latin_titles_do_not_collapse():
    assert resolve(ident("千と千尋の神隠し", 2001), [ident("もののけ姫", 2001)]) == Create()


def test_title_with_no_letters_never_matches_by_title():
    assert resolve(ident("!!!", 2001), [ident("???", 2001)]) == Create()


def test_one_incoming_id_mapping_to_two_titles_is_a_conflict():
    a = ident("Alpha", 2001, tmdb=1)
    b = ident("Beta", 2002, tvdb=2)
    decision = resolve(ident("Gamma", 2003, tmdb=1, tvdb=2), [a, b])
    assert decision == Conflict((a, b))


def test_id_match_whose_other_id_disagrees_is_a_conflict():
    stored = ident("Dune", 2021, tmdb=1, imdb="tt1")
    decision = resolve(ident("Dune", 2021, tmdb=1, imdb="tt2"), [stored])
    assert decision == Conflict((stored,))


def test_two_candidates_matched_by_the_same_id_stored_twice_is_not_a_conflict_for_one_row():
    stored = ident("Dune", 2021, tmdb=1)
    assert resolve(ident("Dune", 2021, tmdb=1), [stored, stored]) == Match(stored)


def test_id_match_beats_title_match_on_another_candidate():
    by_id = ident("Old Name", 1990, tmdb=7)
    by_title = ident("Dune", 2021)
    assert resolve(ident("Dune", 2021, tmdb=7), [by_title, by_id]) == Match(by_id)


def test_first_title_candidate_wins():
    first, second = ident("Dune", 2021), ident("Dune", 2021)
    first = ident("Dune", 2021, tvdb=1)
    second = ident("Dune", 2021, tvdb=2)
    assert resolve(ident("Dune", 2021), [first, second]) == Match(first)
