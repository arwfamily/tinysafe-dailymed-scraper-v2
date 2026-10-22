import json
# Third read (lead): for plant extracts, the CosIng-listed job wins over a marketing benefit
# ("soothing", "antioxidant" as a claim) - we describe what it is used as, not what it promises.
J = {
"ISODODECANE":"emollient","CAPRYLHYDROXAMIC ACID":"preservative_booster","ISOSTEARIC ACID":"dispersing","TRIBEHENIN":"thickener",
"CHAMOMILLA RECUTITA FLOWER EXTRACT":"skin_conditioning","METHYL METHACRYLATE CROSSPOLYMER":"slip","MICROCRYSTALLINE CELLULOSE":"absorbent",
"POLYMETHYL METHACRYLATE":"slip","POLYGONUM AVICULARE EXTRACT":"skin_conditioning","CARTHAMUS TINCTORIUS OLEOSOMES":"emollient",
"CALENDULA OFFICINALIS FLOWER EXTRACT":"skin_conditioning","METHYL DIHYDROABIETATE":"film_former","SYNTHETIC FLUORPHLOGOPITE":"slip",
"ALOE BARBADENSIS LEAF":"skin_conditioning","NYLON-12":"slip","C13-15 ALKANE":"emollient","BIS-ETHYLHEXYLOXYPHENOL METHOXYPHENYL TRIAZINE":"uv_booster",
"C9-12 ALKANE":"emollient","HELIANTHUS ANNUUS EXTRACT":"skin_conditioning","CAMELLIA OLEIFERA LEAF EXTRACT":"skin_conditioning",
"LINOLEIC ACID":"emollient","TRISILOXANE":"slip","PORTULACA OLERACEA EXTRACT":"skin_conditioning","HYDROLYZED JOJOBA ESTERS":"emollient",
"GLYCERYL BEHENATE":"thickener","ORYZANOL":"antioxidant","CARNOSINE":"skin_conditioning","DIAMOND POWDER":"opacifier",
"CALCIUM ALUMINUM BOROSILICATE":"opacifier","LAMINARIA DIGITATA EXTRACT":"skin_conditioning","SODIUM PROPOXYHYDROXYPROPYL THIOSULFATE SILICA":"other",
"VACCINIUM ANGUSTIFOLIUM FRUIT EXTRACT":"skin_conditioning","MELANIN":"other","EQUISETUM ARVENSE EXTRACT":"skin_conditioning",
"STEARYL/OCTYLDODECYL CITRATE CROSSPOLYMER":"film_former","PEG-12 DIMETHICONE":"slip","HYDROLYZED COLLAGEN":"skin_conditioning",
"CALENDULA OFFICINALIS EXTRACT":"skin_conditioning","CYCLODEXTRIN":"other","CAMELLIA SINENSIS LEAF":"skin_conditioning",
"HYDROXYPROPYLTRIMONIUM HYALURONATE":"humectant","PEG/PPG-14/7 DIMETHYL ETHER":"humectant","CHONDRUS CRISPUS EXTRACT":"thickener",
"CALENDULA OFFICINALIS FLOWER":"skin_conditioning","PHYSALIS ANGULATA EXTRACT":"skin_conditioning","PHENYLISOPROPYL DIMETHICONE":"emollient",
"MADECASSOSIDE":"skin_conditioning","3-O-ETHYL ASCORBIC ACID":"antioxidant","OLEA EUROPAEA LEAF EXTRACT":"skin_conditioning",
"OLEA EUROPAEA OIL UNSAPONIFIABLES":"emollient","HIBISCUS ABELMOSCHUS EXTRACT":"skin_conditioning","LAMINARIA SACCHARINA EXTRACT":"skin_conditioning",
"GLYCOL STEARATE":"opacifier","C18-36 ACID GLYCOL ESTER":"thickener","FRUCTOOLIGOSACCHARIDES":"humectant","IMPERATA CYLINDRICA ROOT EXTRACT":"skin_conditioning",
"CENTELLA ASIATICA LEAF EXTRACT":"skin_conditioning","CAESALPINIA SPINOSA FRUIT POD EXTRACT":"film_former","PORPHYRA UMBILICALIS EXTRACT":"skin_conditioning",
"ASIATICOSIDE":"skin_conditioning","POLYGLYCERYL-3 STEARATE/ISOSTEARATE/DIMER DILINOLEATE CROSSPOLYMER":"thickener","ORYZA SATIVA GERM EXTRACT":"skin_conditioning",
"MADECASSIC ACID":"skin_conditioning","SALIX ALBA BARK EXTRACT":"skin_conditioning","ASIATIC ACID":"skin_conditioning",
"HELIANTHUS ANNUUS SEED OIL UNSAPONIFIABLES":"emollient","ACACIA DECURRENS FLOWER CERA":"thickener","ISOBORNYL ACRYLATE":"film_former",
"C30-45 ALKYL CETEARYL DIMETHICONE CROSSPOLYMER":"emollient","SALVIA HISPANICA SEED EXTRACT":"skin_conditioning",
"LAVANDULA ANGUSTIFOLIA FLOWER EXTRACT":"skin_conditioning","POLYBUTENE":"film_former","DEXTRIN":"absorbent","HYDROGENATED POLYBUTENE":"emollient",
"DISILOXANE":"slip","BENZYLIDENE DIMETHOXYDIMETHYLINDANONE":"antioxidant","SODIUM DILAURAMIDOGLUTAMIDE LYSINE":"skin_conditioning",
"GLYCOSAMINOGLYCANS":"humectant","DECARBOXY CARNOSINE HCL":"antioxidant","MENTHA PIPERITA EXTRACT":"skin_conditioning","GLYCERYL BEHENATE/EICOSADIOATE":"thickener",
"PEARL POWDER":"opacifier","SAUSSUREA INVOLUCRATA EXTRACT":"skin_conditioning","SAMBUCUS NIGRA FLOWER EXTRACT":"skin_conditioning",
"TRIFOLIUM PRATENSE FLOWER EXTRACT":"skin_conditioning","PUERARIA LOBATA ROOT EXTRACT":"skin_conditioning","LONICERA CAPRIFOLIUM FLOWER EXTRACT":"skin_conditioning",
"SACCHARUM OFFICINARUM EXTRACT":"skin_conditioning","UNDECYLENOYL GLYCINE":"preservative_booster","PROPYLENE GLYCOL STEARATE":"emulsifier",
"ALCHEMILLA VULGARIS EXTRACT":"skin_conditioning","HYDROXYSTEARIC ACID":"thickener","ETHYL METHICONE":"slip","CETEARYL DIMETHICONE CROSSPOLYMER":"slip",
"ALOE BARBADENSIS LEAF WATER":"base","CHAMOMILLA RECUTITA EXTRACT":"skin_conditioning",
}
d = json.load(open("merged.json"))
miss = [k for k in d["review"] if k not in J]
assert not miss, miss
for k, v in d["review"].items():
    d["accepted"][k] = {"inci": k, "job": J[k], "secondary": None, "confidence": "low", "how": "third_read",
                        "reads": [v["A"]["job"], v["B"]["job"] if v["B"] else None]}
for k, v in d["accepted"].items():
    v.setdefault("how", "two_reads_agree")
json.dump(d["accepted"], open("jobs_final.json", "w"), indent=1)
print(len(d["accepted"]))
