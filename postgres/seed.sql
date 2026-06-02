-- ─────────────────────────────────────────────────────────────
-- Datos de prueba — Ejemplo negocio (20 habitaciones, 3 meses de operación)
-- ─────────────────────────────────────────────────────────────

-- HABITACIONES
INSERT INTO habitaciones (numero, tipo, capacidad, tarifa_base, descripcion) VALUES
('101', 'Simple',  1, 55000,  'Habitación simple, vista interior'),
('102', 'Simple',  1, 55000,  'Habitación simple, vista interior'),
('103', 'Simple',  1, 58000,  'Habitación simple, vista jardín'),
('104', 'Simple',  1, 58000,  'Habitación simple, vista jardín'),
('105', 'Doble',   2, 78000,  'Habitación doble estándar'),
('106', 'Doble',   2, 78000,  'Habitación doble estándar'),
('107', 'Doble',   2, 82000,  'Habitación doble superior'),
('108', 'Doble',   2, 82000,  'Habitación doble superior, vista jardín'),
('201', 'Simple',  1, 55000,  'Habitación simple, piso 2'),
('202', 'Simple',  1, 55000,  'Habitación simple, piso 2'),
('203', 'Simple',  1, 60000,  'Habitación simple, vista calle'),
('204', 'Doble',   2, 80000,  'Habitación doble, piso 2'),
('205', 'Doble',   2, 80000,  'Habitación doble, piso 2'),
('206', 'Doble',   2, 85000,  'Habitación doble superior, piso 2'),
('207', 'Triple',  3, 105000, 'Habitación triple, piso 2'),
('208', 'Triple',  3, 105000, 'Habitación triple, vista jardín'),
('301', 'Suite',   2, 150000, 'Suite junior, sala de estar'),
('302', 'Suite',   2, 150000, 'Suite junior, vista panorámica'),
('303', 'Suite',   4, 200000, 'Suite familiar, dos ambientes'),
('304', 'Suite',   2, 220000, 'Suite presidencial, terraza privada');

-- CANALES DE VENTA
INSERT INTO canales_venta (nombre, comision_pct) VALUES
('Directo',      0.00),
('Booking.com',  15.00),
('Airbnb',       12.00),
('Despegar',     13.00),
('Agencia',      10.00);

-- HUÉSPEDES
INSERT INTO huespedes (nombre, apellido, tipo_documento, documento, nacionalidad, email, telefono) VALUES
('Carlos',     'Muñoz',      'RUT',       '14.234.567-8', 'Chilena',    'carlos.munoz@gmail.com',      '+56 9 8821 1234'),
('Ana',        'Martínez',   'RUT',       '16.789.012-3', 'Chilena',    'ana.martinez@outlook.com',    '+56 9 7732 5678'),
('John',       'Smith',      'Pasaporte', 'US123456',     'Americana',  'john.smith@email.com',        '+1 555 0101'),
('Marie',      'Dupont',     'Pasaporte', 'FR789012',     'Francesa',   'marie.dupont@gmail.com',      '+33 6 1234 5678'),
('Diego',      'Fernández',  'DNI',       '28345678',     'Argentina',  'diego.fern@gmail.com',        '+54 9 11 2345 6789'),
('Valentina',  'Torres',     'RUT',       '17.456.789-0', 'Chilena',    'val.torres@gmail.com',        '+56 9 9901 2345'),
('Pedro',      'Gómez',      'RUT',       '12.345.678-9', 'Chilena',    'pedro.gomez@empresa.cl',      '+56 9 8812 3456'),
('Sofía',      'Herrera',    'RUT',       '15.678.901-2', 'Chilena',    'sofia.h@gmail.com',           '+56 9 7723 4567'),
('James',      'Wilson',     'Pasaporte', 'GB456789',     'Británica',  'j.wilson@email.co.uk',        '+44 7700 900123'),
('Camila',     'Rojas',      'RUT',       '19.012.345-6', 'Chilena',    'camila.rojas@gmail.com',      '+56 9 6634 5678'),
('Roberto',    'Sánchez',    'RUT',       '13.456.789-1', 'Chilena',    'roberto.s@empresa.cl',        '+56 9 9845 6789'),
('Lucía',      'Vargas',     'RUT',       '18.234.567-9', 'Chilena',    'lucia.v@gmail.com',           '+56 9 8756 7890'),
('Miguel',     'Castro',     'DNI',       '32456789',     'Argentina',  'miguel.castro@gmail.com',     '+54 9 261 345 6789'),
('Isabella',   'López',      'Pasaporte', 'CO234567',     'Colombiana', 'isabella.l@gmail.com',        '+57 310 234 5678'),
('Fernando',   'Morales',    'RUT',       '11.234.567-5', 'Chilena',    'f.morales@gmail.com',         '+56 9 7867 8901');

-- RESERVAS (Enero–Marzo 2026)
INSERT INTO reservas (habitacion_id, huesped_id, canal_id, fecha_entrada, fecha_salida, tarifa_noche, estado) VALUES
-- Enero
(1,  1,  1, '2026-01-03', '2026-01-06', 55000,  'checkout'),
(5,  2,  2, '2026-01-05', '2026-01-10', 82000,  'checkout'),
(17, 3,  1, '2026-01-07', '2026-01-14', 160000, 'checkout'),
(8,  4,  3, '2026-01-10', '2026-01-13', 88000,  'checkout'),
(3,  5,  4, '2026-01-12', '2026-01-15', 62000,  'checkout'),
(15, 6,  1, '2026-01-15', '2026-01-20', 110000, 'checkout'),
(6,  7,  2, '2026-01-18', '2026-01-22', 82000,  'checkout'),
(19, 8,  1, '2026-01-20', '2026-01-25', 210000, 'checkout'),
(10, 9,  3, '2026-01-22', '2026-01-24', 58000,  'checkout'),
(7,  10, 5, '2026-01-25', '2026-01-31', 85000,  'checkout'),
-- Febrero
(1,  11, 1, '2026-02-01', '2026-02-04', 55000,  'checkout'),
(18, 12, 2, '2026-02-03', '2026-02-08', 165000, 'checkout'),
(5,  13, 4, '2026-02-05', '2026-02-09', 82000,  'checkout'),
(20, 3,  1, '2026-02-10', '2026-02-17', 230000, 'checkout'),
(9,  4,  3, '2026-02-12', '2026-02-14', 58000,  'checkout'),
(15, 14, 1, '2026-02-14', '2026-02-18', 110000, 'checkout'),
(7,  5,  2, '2026-02-16', '2026-02-20', 88000,  'checkout'),
(3,  6,  1, '2026-02-20', '2026-02-23', 60000,  'checkout'),
(16, 7,  5, '2026-02-22', '2026-02-27', 110000, 'checkout'),
(6,  15, 3, '2026-02-24', '2026-02-28', 82000,  'checkout'),
-- Marzo
(1,  1,  1, '2026-03-01', '2026-03-03', 55000,  'checkout'),
(17, 8,  1, '2026-03-02', '2026-03-07', 160000, 'checkout'),
(5,  9,  2, '2026-03-05', '2026-03-10', 85000,  'checkout'),
(19, 10, 3, '2026-03-07', '2026-03-14', 215000, 'checkout'),
(8,  11, 4, '2026-03-10', '2026-03-13', 85000,  'checkout'),
(3,  12, 1, '2026-03-12', '2026-03-15', 60000,  'checkout'),
(15, 13, 5, '2026-03-15', '2026-03-20', 112000, 'checkout'),
(20, 3,  1, '2026-03-18', '2026-03-25', 230000, 'checkout'),
(7,  14, 2, '2026-03-20', '2026-03-24', 88000,  'checkout'),
(6,  15, 1, '2026-03-22', '2026-03-26', 82000,  'checkout'),
-- Abril (en curso)
(1,  2,  1, '2026-04-01', '2026-04-04', 55000,  'checkout'),
(18, 4,  3, '2026-04-03', '2026-04-08', 165000, 'checkin'),
(5,  6,  2, '2026-04-05', '2026-04-10', 85000,  'checkin'),
(17, 7,  1, '2026-04-08', '2026-04-12', 160000, 'checkout'),
(9,  8,  4, '2026-04-10', '2026-04-14', 60000,  'checkin'),
(20, 9,  1, '2026-04-12', '2026-04-18', 230000, 'checkin'),
(15, 10, 5, '2026-04-13', '2026-04-16', 112000, 'confirmada'),
(7,  11, 2, '2026-04-15', '2026-04-18', 88000,  'confirmada');

-- PAGOS
INSERT INTO pagos (reserva_id, fecha, monto, metodo, concepto, estado) VALUES
-- Enero
(1,  '2026-01-06', 165000,  'tarjeta',      'hospedaje',  'pagado'),
(2,  '2026-01-05', 164000,  'tarjeta',      'anticipo',   'pagado'),
(2,  '2026-01-10', 246000,  'tarjeta',      'hospedaje',  'pagado'),
(3,  '2026-01-14', 1120000, 'transferencia','hospedaje',  'pagado'),
(4,  '2026-01-13', 264000,  'tarjeta',      'hospedaje',  'pagado'),
(5,  '2026-01-15', 186000,  'efectivo',     'hospedaje',  'pagado'),
(6,  '2026-01-20', 550000,  'tarjeta',      'hospedaje',  'pagado'),
(7,  '2026-01-22', 328000,  'tarjeta',      'hospedaje',  'pagado'),
(8,  '2026-01-25', 1050000, 'transferencia','hospedaje',  'pagado'),
(9,  '2026-01-24', 116000,  'efectivo',     'hospedaje',  'pagado'),
(10, '2026-01-31', 510000,  'tarjeta',      'hospedaje',  'pagado'),
-- Febrero
(11, '2026-02-04', 165000,  'efectivo',     'hospedaje',  'pagado'),
(12, '2026-02-08', 825000,  'tarjeta',      'hospedaje',  'pagado'),
(13, '2026-02-09', 328000,  'tarjeta',      'hospedaje',  'pagado'),
(14, '2026-02-17', 1610000, 'transferencia','hospedaje',  'pagado'),
(15, '2026-02-14', 116000,  'tarjeta',      'hospedaje',  'pagado'),
(16, '2026-02-18', 440000,  'tarjeta',      'hospedaje',  'pagado'),
(17, '2026-02-20', 352000,  'tarjeta',      'hospedaje',  'pagado'),
(18, '2026-02-23', 180000,  'efectivo',     'hospedaje',  'pagado'),
(19, '2026-02-27', 550000,  'tarjeta',      'hospedaje',  'pagado'),
(20, '2026-02-28', 328000,  'tarjeta',      'hospedaje',  'pagado'),
-- Marzo
(21, '2026-03-03', 110000,  'efectivo',     'hospedaje',  'pagado'),
(22, '2026-03-07', 800000,  'transferencia','hospedaje',  'pagado'),
(23, '2026-03-10', 425000,  'tarjeta',      'hospedaje',  'pagado'),
(24, '2026-03-14', 1505000, 'transferencia','hospedaje',  'pagado'),
(25, '2026-03-13', 255000,  'tarjeta',      'hospedaje',  'pagado'),
(26, '2026-03-15', 180000,  'efectivo',     'hospedaje',  'pagado'),
(27, '2026-03-20', 560000,  'tarjeta',      'hospedaje',  'pagado'),
(28, '2026-03-25', 1610000, 'transferencia','hospedaje',  'pagado'),
(29, '2026-03-24', 352000,  'tarjeta',      'hospedaje',  'pagado'),
(30, '2026-03-26', 328000,  'tarjeta',      'hospedaje',  'pagado'),
-- Abril
(31, '2026-04-04', 165000,  'efectivo',     'hospedaje',  'pagado'),
(32, '2026-04-03', 400000,  'tarjeta',      'anticipo',   'pagado'),
(34, '2026-04-12', 640000,  'transferencia','hospedaje',  'pagado');

-- CATEGORÍAS DE GASTO
INSERT INTO categorias_gasto (nombre, descripcion) VALUES
('Personal',       'Sueldos, honorarios y beneficios del personal'),
('Mantenimiento',  'Reparaciones, limpieza y mantención de instalaciones'),
('Suministros',    'Amenities, ropa de cama, productos de limpieza'),
('Servicios',      'Electricidad, agua, internet, telefonía'),
('Marketing',      'Publicidad, comisiones OTA, materiales promocionales'),
('Frigobar',       'Reposición de bebidas y snacks del frigobar'),
('Administración', 'Contabilidad, seguros, gastos bancarios');

-- GASTOS (Enero–Abril 2026)
INSERT INTO gastos (categoria_id, fecha, descripcion, monto, proveedor) VALUES
-- Personal
(1, '2026-01-31', 'Sueldo recepcionista enero',        650000, 'Nómina interna'),
(1, '2026-01-31', 'Sueldo camarera enero',             580000, 'Nómina interna'),
(1, '2026-01-31', 'Sueldo administración enero',       850000, 'Nómina interna'),
(1, '2026-02-28', 'Sueldo recepcionista febrero',      650000, 'Nómina interna'),
(1, '2026-02-28', 'Sueldo camarera febrero',           580000, 'Nómina interna'),
(1, '2026-02-28', 'Sueldo administración febrero',     850000, 'Nómina interna'),
(1, '2026-03-31', 'Sueldo recepcionista marzo',        650000, 'Nómina interna'),
(1, '2026-03-31', 'Sueldo camarera marzo',             580000, 'Nómina interna'),
(1, '2026-03-31', 'Sueldo administración marzo',       850000, 'Nómina interna'),
-- Servicios
(4, '2026-01-10', 'Electricidad enero',                185000, 'Distribuidora eléctrica'),
(4, '2026-01-10', 'Agua enero',                         42000, 'Empresa sanitaria'),
(4, '2026-01-10', 'Internet y telefonía enero',          35000, 'Proveedor telecomunicaciones'),
(4, '2026-02-10', 'Electricidad febrero',               192000, 'Distribuidora eléctrica'),
(4, '2026-02-10', 'Agua febrero',                        45000, 'Empresa sanitaria'),
(4, '2026-02-10', 'Internet y telefonía febrero',         35000, 'Proveedor telecomunicaciones'),
(4, '2026-03-10', 'Electricidad marzo',                 178000, 'Distribuidora eléctrica'),
(4, '2026-03-10', 'Agua marzo',                          40000, 'Empresa sanitaria'),
(4, '2026-03-10', 'Internet y telefonía marzo',           35000, 'Proveedor telecomunicaciones'),
-- Suministros
(3, '2026-01-08', 'Amenities y productos baño',         95000, 'Proveedor local'),
(3, '2026-01-08', 'Ropa de cama y toallas',            145000, 'Textiles y suministros'),
(3, '2026-02-06', 'Amenities y productos baño',         88000, 'Proveedor local'),
(3, '2026-03-05', 'Amenities y productos baño',         92000, 'Proveedor local'),
(3, '2026-03-05', 'Ropa de cama — reposición',          78000, 'Textiles y suministros'),
-- Mantenimiento
(2, '2026-01-15', 'Reparación aire acondicionado 301', 120000, 'Técnico climatización'),
(2, '2026-02-20', 'Pintura habitaciones 201-203',      180000, 'Empresa pintura'),
(2, '2026-03-12', 'Reparación plomería piso 1',         65000, 'Gasfíter'),
-- Marketing
(5, '2026-01-31', 'Comisiones Booking.com enero',      145000, 'Booking.com'),
(5, '2026-01-31', 'Comisiones Airbnb enero',            82000, 'Airbnb'),
(5, '2026-02-28', 'Comisiones Booking.com febrero',    168000, 'Booking.com'),
(5, '2026-02-28', 'Comisiones Airbnb febrero',          95000, 'Airbnb'),
(5, '2026-03-31', 'Comisiones Booking.com marzo',      152000, 'Booking.com'),
(5, '2026-03-31', 'Comisiones Airbnb marzo',            88000, 'Airbnb'),
-- Frigobar
(6, '2026-01-20', 'Reposición bebidas y snacks',        68000, 'Distribuidora'),
(6, '2026-02-18', 'Reposición bebidas y snacks',        72000, 'Distribuidora'),
(6, '2026-03-15', 'Reposición bebidas y snacks',        65000, 'Distribuidora'),
-- Administración
(7, '2026-01-31', 'Honorarios contabilidad enero',      85000, 'Contador externo'),
(7, '2026-02-28', 'Honorarios contabilidad febrero',    85000, 'Contador externo'),
(7, '2026-03-31', 'Honorarios contabilidad marzo',      85000, 'Contador externo'),
(7, '2026-01-31', 'Seguro comercial cuota enero',        95000, 'Compañía seguros');

-- CONSUMOS FRIGOBAR
-- costo_unitario: precio de compra aprox. 40-50% del precio de venta
INSERT INTO consumos_frigobar (reserva_id, fecha, descripcion, cantidad, precio_unitario, costo_unitario) VALUES
(3,  '2026-01-09',  'Agua mineral',   4, 2500, 900),
(3,  '2026-01-11',  'Cerveza',        6, 3500, 1400),
(3,  '2026-01-12',  'Snack mixto',    2, 2800, 1200),
(8,  '2026-01-21',  'Agua mineral',   2, 2500, 900),
(8,  '2026-01-22',  'Jugo naranja',   3, 3000, 1100),
(14, '2026-02-12',  'Agua mineral',   6, 2500, 900),
(14, '2026-02-13',  'Cerveza',        4, 3500, 1400),
(14, '2026-02-15',  'Vino tinto',     2, 8500, 3800),
(14, '2026-02-16',  'Snack mixto',    3, 2800, 1200),
(24, '2026-03-09',  'Agua mineral',   8, 2500, 900),
(24, '2026-03-10',  'Cerveza',        6, 3500, 1400),
(24, '2026-03-12',  'Vino tinto',     1, 8500, 3800),
(28, '2026-03-20',  'Agua mineral',   4, 2500, 900),
(28, '2026-03-22',  'Cerveza',        8, 3500, 1400),
(28, '2026-03-23',  'Snack mixto',    4, 2800, 1200),
(36, '2026-04-13',  'Agua mineral',   2, 2500, 900),
(36, '2026-04-14',  'Cerveza',        3, 3500, 1400);

INSERT INTO consumos_servicios (reserva_id, fecha, servicio, descripcion, cantidad, precio_unitario, costo_unitario) VALUES
-- Enero
(3,  '2026-01-10',  'Lavandería',      '2 camisas + 1 pantalón',    1, 8500,  3500),
(8,  '2026-01-22',  'Lavandería',      'Ropa de cama extra',         1, 6000,  2500),
(8,  '2026-01-23',  'Estacionamiento', 'Día completo',               2, 5000,  1000),
-- Febrero
(14, '2026-02-13',  'Lavandería',      '3 camisas + 1 vestido',      1, 12000, 4500),
(14, '2026-02-14',  'Estacionamiento', 'Día completo',               3, 5000,  1000),
(14, '2026-02-15',  'Traslado',        'Transfer aeropuerto ida',     1, 35000, 18000),
(19, '2026-02-21',  'Lavandería',      '2 pantalones + 2 camisas',   1, 9500,  3500),
-- Marzo
(24, '2026-03-10',  'Lavandería',      'Ropa formal 4 prendas',      1, 14000, 5000),
(24, '2026-03-11',  'Estacionamiento', 'Día completo',               2, 5000,  1000),
(28, '2026-03-21',  'Lavandería',      '3 camisas',                  1, 8500,  3500),
(28, '2026-03-22',  'Traslado',        'Transfer aeropuerto vuelta', 1, 35000, 18000),
(28, '2026-03-23',  'Estacionamiento', 'Día completo',               1, 5000,  1000),
-- Abril
(36, '2026-04-13',  'Lavandería',      '2 camisas + 1 pantalón',    1, 8500,  3500),
(36, '2026-04-14',  'Estacionamiento', 'Día completo',               1, 5000,  1000);

-- MOVIMIENTOS BANCARIOS (cartola de ejemplo, Enero 2026)
-- Dos abonos que calzan con pagos existentes y un cargo sin respaldo.
INSERT INTO movimientos_bancarios (fecha, glosa, monto, referencia) VALUES
('2026-01-06', 'Abono cliente Booking',      165000,  'OP-1001'),
('2026-01-15', 'Transferencia recibida',     1120000, 'OP-1002'),
('2026-01-18', 'Comisión mantención banco',  -77777,  'OP-1003');
