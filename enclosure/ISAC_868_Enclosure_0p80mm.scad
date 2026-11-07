// ISAC_868_Enclosure_0p80mm.scad -- Rev E.5 Uniform-Flat-Roof Waterproof Enclosure
// Coordinate System: Right-Handed AuxOrigin / Gerber / STEP (+X East 0..90, +Y North 0..40, +Z Up above F.Cu)
// Key Rev E.5 Features (1:1 synchronized with gen_enclosure.py):
//   1. 100% Uniform Flat Waterproof Top Cover (z_top = +8.50 mm across entire roof; J1..J5 DNP; zero domes or roof slots!)
//   2. Open-East Self-Draining 0.80 mm UV-Stabilized ASA / PETG Sensing Deck (X = 74.60..92.85 mm, 0.00 mm dam lip!)
//   3. Symmetric 95.70 x 45.70 mm Outer Shell with Compliant Z_SKIRT_BOT = -1.44 mm (+0.16 mm tolerance gap) &
//      Continuous 360-Deg Parker ORD 5700 Face-Seal O-Ring Groove (1.80 x 0.76 mm -> 0.92 mm gland, 23.3% squeeze, 68.3% fill)
$fn = 48;

w_pcb = 90.00;  h_pcb = 40.00;  t_pcb = 1.60;
z_skirt_bot = -1.44;            clr = 0.25;     wall = 2.60;
groove_margin = 0.400;          groove_w = 1.80;  groove_d = 0.76;
groove_r_in = 0.60;             groove_r_out = 2.40;
t_asa_window = 0.80;

win_x0 = 74.60; win_x1 = 86.60;
win_y0 = 7.65;  win_y1 = 20.20;
boss_x0 = 73.60; boss_x1 = 87.60;
boss_y0 = 6.85;  boss_y1 = 20.60;

holes = [[3.5, 3.5], [86.5, 3.5], [3.5, 36.5], [86.5, 36.5]];

module rounded_rect_2d(x0, y0, w, h, r) {
    offset(r = r)
        translate([x0 + r, y0 + r])
            square([w - 2*r, h - 2*r]);
}

module parker_oring_groove_2d() {
    difference() {
        rounded_rect_2d(-clr - wall + groove_margin, -clr - wall + groove_margin,
                        w_pcb + 2*(clr + wall - groove_margin),
                        h_pcb + 2*(clr + wall - groove_margin),
                        groove_r_out);
        rounded_rect_2d(-clr - wall + groove_margin + groove_w, -clr - wall + groove_margin + groove_w,
                        w_pcb + 2*(clr + wall - groove_margin - groove_w),
                        h_pcb + 2*(clr + wall - groove_margin - groove_w),
                        groove_r_in);
    }
}

module lid_0p80mm() {
    difference() {
        // 100% uniform flat solid-roof outer shell (95.70 x 45.70 mm, z = -1.44..+8.50 mm compliant skirt)
        translate([-clr - wall, -clr - wall, z_skirt_bot])
            cube([w_pcb + 2*(clr + wall), h_pcb + 2*(clr + wall), 8.50 - z_skirt_bot]);
        // Electronics bay internal cavity (X = 0..50 mm, uniform solid ceiling z = 6.50 mm)
        difference() {
            translate([-clr, -clr, -t_pcb - 0.1])
                cube([50.0 + clr, h_pcb + 2*clr, 6.50 + t_pcb + 0.1]);
            translate([-clr, -clr, 0]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 8.0]);
            translate([-clr, 36.5 - 3.1, 0]) cube([5.40 + clr, 3.5 + 3.1 + clr, 8.0]);
        }
        // Antenna free-air cavity (X = 50..90 mm, ceiling z = 4.50 mm)
        difference() {
            translate([50.0, -clr, -t_pcb - 0.1])
                cube([40.0 + clr, h_pcb + 2*clr, 4.50 + t_pcb + 0.1]);
            translate([boss_x0, boss_y0, 0])
                cube([boss_x1 - boss_x0, boss_y1 - boss_y0, 5.0]);
            translate([boss_x1, win_y0, 0.16])
                cube([(w_pcb + clr) - boss_x1, win_y1 - win_y0, 5.0]);
            translate([86.5 - 3.1, -clr, 0]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 5.0]);
            translate([86.5 - 3.1, 36.5 - 3.1, 0]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 5.0]);
        }
        // Open-East self-draining runoff cut (flush z_top = +0.80 mm all the way through X = 92.85 mm!)
        translate([win_x0, win_y0, t_asa_window])
            cube([(w_pcb + clr + wall + 0.2) - win_x0, win_y1 - win_y0, 9.0]);
        // 4 x M2.5 Nylon screw through-holes
        for (h = holes)
            translate([h[0], h[1], -t_pcb - 1]) cylinder(d = 2.80, h = 14.0);
    }
}

module base_tray_option_a_slim() {
    difference() {
        translate([-clr - wall, -clr - wall, -7.60])
            cube([w_pcb + 2*(clr + wall), h_pcb + 2*(clr + wall), 6.00]);
        // Continuous 360-degree unbroken 1.80 x 0.76 mm Parker ORD 5700 concentric-corner face-seal O-ring groove
        translate([0, 0, -t_pcb - groove_d])
            linear_extrude(height = groove_d + 0.1) parker_oring_groove_2d();
        // Main 4.00 mm unloaded air pocket
        difference() {
            translate([-clr, -clr, -5.60])
                cube([w_pcb + 2*clr, h_pcb + 2*clr, 4.20]);
            translate([-clr, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([-clr, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([7.00, 4.70, -5.70])
                cube([39.20, 29.00, 2.94]);
        }
        // Option A 302535/352535 LiPo pocket + under-PCB J2 direct-solder wire-relief channel (-6.16 mm)
        translate([8.60, 6.30, -6.16])
            cube([36.00, 25.80, 4.00]);
        translate([7.40, 31.50, -6.16])
            cube([7.60, 6.15, 4.70]);
        // 4 x M2.5 Nylon screw through-holes
        for (h = holes)
            translate([h[0], h[1], -10.0]) cylinder(d = 2.80, h = 10.0);
    }
}

module base_tray_battery() {
    difference() {
        union() {
            translate([-clr - wall, -clr - wall, -7.60])
                cube([w_pcb + 2*(clr + wall), h_pcb + 2*(clr + wall), 6.00]);
            translate([6.60, 9.60, -19.10])
                cube([42.80, 19.20, 13.50]);
        }
        // Continuous 360-degree unbroken 1.80 x 0.76 mm Parker ORD 5700 concentric-corner face-seal O-ring groove
        translate([0, 0, -t_pcb - groove_d])
            linear_extrude(height = groove_d + 0.1) parker_oring_groove_2d();
        difference() {
            translate([-clr, -clr, -5.60])
                cube([w_pcb + 2*clr, h_pcb + 2*clr, 4.20]);
            translate([-clr, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([-clr, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, -clr, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
            translate([86.5 - 3.1, 36.5 - 3.1, -5.70]) cube([3.5 + 3.1 + clr, 3.5 + 3.1 + clr, 4.15]);
        }
        translate([8.60, 11.60, -17.10])
            cube([38.80, 15.20, 11.70]);
        translate([8.60, 6.30, -6.16])
            cube([36.00, 25.80, 4.00]);
        translate([7.40, 31.50, -6.16])
            cube([7.60, 6.15, 4.70]);
        for (h = holes)
            translate([h[0], h[1], -20.0]) cylinder(d = 2.80, h = 20.0);
    }
}

lid_0p80mm();
// translate([0, 0, -12]) base_tray_battery();
