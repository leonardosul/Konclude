# FIBO check

This branch is not meant to be merged. It holds one workflow (`.github/workflows/fibo-check.yml`) that compares two Konclude builds:

- `konclude/Konclude` master;
- the fix branch (`fix/datetimestamp-crash-and-parsing` by default; another one can be chosen when the workflow is run by hand).

Both are compiled the same way as upstream's Ubuntu job (Qt 5.15.2, `KoncludeWithoutRedland.pro`). Both are then run on:

- the small cases in `cases/`;
- the FIBO closure, built from the public release: edmcouncil/fibo tag `master_2026Q3`, merged by ROBOT 1.9.10 with the OMG Commons, LCC and MVF modules it imports, which ROBOT fetches from omg.org;
- the FIBO closure plus each contradiction in `injections/`.

HermiT, run through ROBOT on FIBO's terms with the individuals removed, gives the reference count of unsatisfiable classes. The job summary shows the table, and the run fails if the fix branch does not give every expected answer.

To run it locally (Linux, with Konclude, Java 17 and `robot.jar`):

```
git clone --depth 1 --branch master_2026Q3 https://github.com/edmcouncil/fibo.git
java -Xmx6G -jar robot.jar merge --catalog fibo/catalog-v001.xml --input fibo/AboutFIBOProd.rdf --output closure.ofn
python3 fibo-check/check.py --build master=/path/to/master/Konclude --build branch=/path/to/branch/Konclude \
  --fibo closure.ofn --out summary.md
```
