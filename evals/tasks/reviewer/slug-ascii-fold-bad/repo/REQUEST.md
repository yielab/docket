# Request

slugify must fold accented letters to their ASCII base letter instead of treating them as
separators: 'Cafe Creme' and 'Café Crème' both give 'cafe-creme'.
