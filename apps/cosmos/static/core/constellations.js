/* The 88 IAU constellations by the three-letter abbreviation HYG uses in its
 * "con" column: [name, genitive]. Star names use the genitive
 * ("Alpha Centauri", "61 Cygni"). */

export const CONSTELLATION_TABLE = {
  And: ["Andromeda", "Andromedae"], Ant: ["Antlia", "Antliae"], Aps: ["Apus", "Apodis"],
  Aqr: ["Aquarius", "Aquarii"], Aql: ["Aquila", "Aquilae"], Ara: ["Ara", "Arae"],
  Ari: ["Aries", "Arietis"], Aur: ["Auriga", "Aurigae"], Boo: ["Boötes", "Boötis"],
  Cae: ["Caelum", "Caeli"], Cam: ["Camelopardalis", "Camelopardalis"], Cnc: ["Cancer", "Cancri"],
  CVn: ["Canes Venatici", "Canum Venaticorum"], CMa: ["Canis Major", "Canis Majoris"],
  CMi: ["Canis Minor", "Canis Minoris"], Cap: ["Capricornus", "Capricorni"],
  Car: ["Carina", "Carinae"], Cas: ["Cassiopeia", "Cassiopeiae"], Cen: ["Centaurus", "Centauri"],
  Cep: ["Cepheus", "Cephei"], Cet: ["Cetus", "Ceti"], Cha: ["Chamaeleon", "Chamaeleontis"],
  Cir: ["Circinus", "Circini"], Col: ["Columba", "Columbae"], Com: ["Coma Berenices", "Comae Berenices"],
  CrA: ["Corona Australis", "Coronae Australis"], CrB: ["Corona Borealis", "Coronae Borealis"],
  Crv: ["Corvus", "Corvi"], Crt: ["Crater", "Crateris"], Cru: ["Crux", "Crucis"],
  Cyg: ["Cygnus", "Cygni"], Del: ["Delphinus", "Delphini"], Dor: ["Dorado", "Doradus"],
  Dra: ["Draco", "Draconis"], Equ: ["Equuleus", "Equulei"], Eri: ["Eridanus", "Eridani"],
  For: ["Fornax", "Fornacis"], Gem: ["Gemini", "Geminorum"], Gru: ["Grus", "Gruis"],
  Her: ["Hercules", "Herculis"], Hor: ["Horologium", "Horologii"], Hya: ["Hydra", "Hydrae"],
  Hyi: ["Hydrus", "Hydri"], Ind: ["Indus", "Indi"], Lac: ["Lacerta", "Lacertae"],
  Leo: ["Leo", "Leonis"], LMi: ["Leo Minor", "Leonis Minoris"], Lep: ["Lepus", "Leporis"],
  Lib: ["Libra", "Librae"], Lup: ["Lupus", "Lupi"], Lyn: ["Lynx", "Lyncis"], Lyr: ["Lyra", "Lyrae"],
  Men: ["Mensa", "Mensae"], Mic: ["Microscopium", "Microscopii"], Mon: ["Monoceros", "Monocerotis"],
  Mus: ["Musca", "Muscae"], Nor: ["Norma", "Normae"], Oct: ["Octans", "Octantis"],
  Oph: ["Ophiuchus", "Ophiuchi"], Ori: ["Orion", "Orionis"], Pav: ["Pavo", "Pavonis"],
  Peg: ["Pegasus", "Pegasi"], Per: ["Perseus", "Persei"], Phe: ["Phoenix", "Phoenicis"],
  Pic: ["Pictor", "Pictoris"], Psc: ["Pisces", "Piscium"], PsA: ["Piscis Austrinus", "Piscis Austrini"],
  Pup: ["Puppis", "Puppis"], Pyx: ["Pyxis", "Pyxidis"], Ret: ["Reticulum", "Reticuli"],
  Sge: ["Sagitta", "Sagittae"], Sgr: ["Sagittarius", "Sagittarii"], Sco: ["Scorpius", "Scorpii"],
  Scl: ["Sculptor", "Sculptoris"], Sct: ["Scutum", "Scuti"], Ser: ["Serpens", "Serpentis"],
  Sex: ["Sextans", "Sextantis"], Tau: ["Taurus", "Tauri"], Tel: ["Telescopium", "Telescopii"],
  Tri: ["Triangulum", "Trianguli"], TrA: ["Triangulum Australe", "Trianguli Australis"],
  Tuc: ["Tucana", "Tucanae"], UMa: ["Ursa Major", "Ursae Majoris"], UMi: ["Ursa Minor", "Ursae Minoris"],
  Vel: ["Vela", "Velorum"], Vir: ["Virgo", "Virginis"], Vol: ["Volans", "Volantis"],
  Vul: ["Vulpecula", "Vulpeculae"],
}; // prettier-ignore

export const CONSTELLATIONS = Object.fromEntries(
  Object.entries(CONSTELLATION_TABLE).map(([abbr, [name]]) => [abbr, name]),
);

const GREEK = {
  Alp: "α", Bet: "β", Gam: "γ", Del: "δ", Eps: "ε", Zet: "ζ", Eta: "η", The: "θ",
  Iot: "ι", Kap: "κ", Lam: "λ", Mu: "μ", Nu: "ν", Xi: "ξ", Omi: "ο", Pi: "π",
  Rho: "ρ", Sig: "σ", Tau: "τ", Ups: "υ", Phi: "φ", Chi: "χ", Psi: "ψ", Ome: "ω",
}; // prettier-ignore

const SUPERSCRIPT = ["⁰", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"];

/* HYG's catalogue names, written the way astronomers write them:
 *   "Alp Cen" -> "α Centauri", "Kap-1 Scl" -> "κ¹ Sculptoris",
 *   "29 Psc" -> "29 Piscium". Anything else comes back unchanged. */
export function prettyStarName(name) {
  const m = /^([A-Za-z]{1,3}|\d+)(?:-(\d+))?\s+([A-Za-z]{3})$/.exec(name);
  const con = m && CONSTELLATION_TABLE[m[3]];
  if (!con) return name;
  const letter = /^\d+$/.test(m[1]) ? m[1] : GREEK[m[1]];
  if (!letter) return name;
  const index = m[2] ? m[2].split("").map((d) => SUPERSCRIPT[Number(d)]).join("") : "";
  return `${letter}${index} ${con[1]}`;
}
