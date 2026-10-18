p = "app/modules/review_engine/classifier.py"
s = open(p, encoding="utf-8").read()
s = s.replace('\\"', '"')
open(p, "w", encoding="utf-8").write(s)
# verify syntax
import ast
ast.parse(s)
print("syntax OK")