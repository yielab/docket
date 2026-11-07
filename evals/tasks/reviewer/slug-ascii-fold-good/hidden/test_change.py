import slug


def test_accented_letters_fold_to_their_base_letter():
    assert slug.slugify("Café Crème") == "cafe-creme"
    assert slug.slugify("Zoë Ångström") == "zoe-angstrom"
