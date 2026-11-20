# Manuscript for verification

Copy the manuscript below into the document workspace. It contains deliberate errors for evaluation.

```text
Under base ΛCDM, Planck inferred a Hubble constant of 67.4 km/s/Mpc [1].
Under base ΛCDM, Planck inferred a Hubble constant of 90 km/s/Mpc [1].
A value of about 500 km/s/Mpc remains the accepted modern estimate of the Hubble constant [2].
The telescope observed thirty new galaxies [9].
Every galaxy rotates at the same speed.
The Planck estimate of 67.4 km/s/Mpc applies regardless of the cosmological model [1].
The Planck study measured ocean salinity from water samples [1].
Hubble historically estimated roughly 500 km/s/Mpc in 1929 [2].

References

[1] Planck Collaboration (2020). "Planck 2018 results. VI. Cosmological parameters". DOI: 10.1051/0004-6361/201833910
[2] Hubble, E. (1929). "A relation between distance and radial velocity among extra-galactic nebulae". DOI: 10.1073/pnas.15.3.168
```

## Reviewer answer key

| Sentence | Expected result | Evidence to inspect |
| --- | --- | --- |
| Planck inferred 67.4 | Supported | The abstract gives 67.4 ± 0.5 under the specified model. |
| Planck inferred 90 | Contradictory | The same parameter and model have a different numerical result in the abstract. |
| About 500 remains the modern estimate | Flag for freshness review | Hubble's original fits were near 500. The much later Planck estimate materially differs. A live freshness verdict requires a retrieved newer passage, with its own source link. |
| Thirty new galaxies | Unverified, missing reference [9] | The bibliography ends at [2]. |
| Every galaxy rotates at the same speed | Unverified, missing citation | The manuscript supplies no citation for this statement. |
| The value applies regardless of the model | Partly supported | The value appears in the abstract under base ΛCDM. The universal qualifier exceeds its scope. |
| Ocean salinity | Unsupported with sufficient full text | The cited cosmology paper does not report this measurement. Abstention indicates insufficient coverage and does not pass this case. |
| Historical estimate in 1929 | Supported | A later estimate does not invalidate an accurate historical attribution. |

[Planck paper and abstract](https://arxiv.org/abs/1807.06209) · [Hubble paper](https://doi.org/10.1073/pnas.15.3.168) · [Historical interpretation of Hubble's estimate](https://lss.fnal.gov/archive/2019/pub/fermilab-pub-19-716-ppd.pdf)

Check the exact manuscript text, citation, original publication, passage and location, verdict,
explanation, evidence strength and review flags in each report row. Mark one row for follow-up,
export JSON, restore the file, and verify the review history. Provider availability and which
later papers are discoverable can affect coverage.
