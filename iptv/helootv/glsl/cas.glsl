// Heloo TV — kontrast uyarlamalı keskinleştirme (AMD FidelityFX CAS yönteminin sade uyarlaması, MIT).
// Kenarları belirginleştirir, düz alanlarda gürültüyü büyütmez. Güç: --glsl-shader-opts=cas_sharpness=0..1

//!PARAM cas_sharpness
//!DESC Keskinlik (0 = kapalı, 1 = en güçlü)
//!TYPE float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.4

//!HOOK OUTPUT
//!BIND HOOKED
//!DESC Heloo TV CAS keskinlestirme
//!WHEN cas_sharpness 0 >

vec4 hook() {
    vec4 c = HOOKED_texOff(vec2(0.0, 0.0));
    vec3 e = c.rgb;
    vec3 b = HOOKED_texOff(vec2(0.0, -1.0)).rgb;
    vec3 d = HOOKED_texOff(vec2(-1.0, 0.0)).rgb;
    vec3 f = HOOKED_texOff(vec2(1.0, 0.0)).rgb;
    vec3 h = HOOKED_texOff(vec2(0.0, 1.0)).rgb;
    vec3 mn = min(min(min(d, e), min(f, b)), h);
    vec3 mx = max(max(max(d, e), max(f, b)), h);
    vec3 amp = sqrt(clamp(min(mn, 2.0 - mx) / max(mx, vec3(1e-5)), 0.0, 1.0));
    vec3 w = amp * (-1.0 / mix(8.0, 5.0, cas_sharpness));
    vec3 o = ((b + d + f + h) * w + e) / (1.0 + 4.0 * w);
    return vec4(max(o, vec3(0.0)), c.a);
}
