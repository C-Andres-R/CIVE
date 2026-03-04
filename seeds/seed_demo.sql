-- Seed demo minimo para CIVE.
-- Uso recomendado:
-- 1) Crear la base y aplicar migraciones actuales.
-- 2) Ejecutar este archivo sobre una base destinada a demo.
--
-- Credenciales demo:
-- administrador@cive.demo / DemoCive2026!
-- veterinario@cive.demo   / DemoCive2026!
-- cliente@cive.demo       / DemoCive2026!

START TRANSACTION;

SET @admin_email = 'administrador@cive.demo';
SET @vet_email = 'veterinario@cive.demo';
SET @cliente_email = 'cliente@cive.demo';
SET @mascota_nombre = 'Luna Demo';

-- Limpiamos primero cualquier rastro previo del mismo dataset demo.
SET @cliente_id = (
    SELECT id FROM usuarios WHERE correo = @cliente_email LIMIT 1
);
SET @vet_id = (
    SELECT id FROM usuarios WHERE correo = @vet_email LIMIT 1
);
SET @mascota_id = (
    SELECT id
    FROM mascotas
    WHERE dueno_id = @cliente_id AND nombre = @mascota_nombre
    LIMIT 1
);

DELETE FROM recordatorios_citas
WHERE cita_id IN (
    SELECT id
    FROM citas
    WHERE cliente_id = @cliente_id
       OR veterinario_id = @vet_id
       OR mascota_id = @mascota_id
);

DELETE FROM citas
WHERE cliente_id = @cliente_id
   OR veterinario_id = @vet_id
   OR mascota_id = @mascota_id;

DELETE FROM facturacion
WHERE cliente_id = @cliente_id;

DELETE FROM mascotas
WHERE id = @mascota_id;

DELETE FROM usuarios
WHERE correo IN (@admin_email, @vet_email, @cliente_email);

-- Roles base requeridos por la aplicacion.
INSERT INTO roles (nombre)
VALUES
    ('administrador'),
    ('veterinario'),
    ('cliente')
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);

SET @rol_admin_id = (
    SELECT id FROM roles WHERE LOWER(nombre) = 'administrador' LIMIT 1
);
SET @rol_vet_id = (
    SELECT id FROM roles WHERE LOWER(nombre) = 'veterinario' LIMIT 1
);
SET @rol_cliente_id = (
    SELECT id FROM roles WHERE LOWER(nombre) = 'cliente' LIMIT 1
);

-- Usuarios demo con hash Werkzeug/scrypt.
INSERT INTO usuarios (
    nombre,
    nombres,
    apellido_paterno,
    apellido_materno,
    correo,
    contrasena,
    domicilio,
    calle,
    numero,
    colonia,
    codigo_postal,
    estado,
    entidad,
    telefono,
    razon_inactivacion,
    activo,
    eliminado,
    rol_id
) VALUES
    (
        'Admin Demo',
        'Admin',
        'Demo',
        NULL,
        @admin_email,
        'scrypt:32768:8:1$FChI0MTDIWe3EKLb$e12dede9a98050f5e00bb467da12b97b80880f9fb5d0baab4fb8628e80d4518fcde6807524744c39d395d293eb7009d59e06b66e888dfee58c155913dd7ae0ed',
        'Sucursal Central Demo',
        'Av. Central',
        '100',
        'Centro',
        '55000',
        'Estado de Mexico',
        'Ecatepec',
        '+52 55 1000 0001',
        NULL,
        1,
        0,
        @rol_admin_id
    ),
    (
        'Dra. Sofia Demo',
        'Sofia',
        'Demo',
        NULL,
        @vet_email,
        'scrypt:32768:8:1$3vVej0tZfOYspqGj$873f62252b39d47bcef5f62120c2a8d84da5af0248a14359f6b571e723cda45d30ede286e0e501e832a405f27267a45638c88302ffe4d1050fb1a99652f6e56b',
        'Consultorio 2',
        'Calle Salud',
        '22',
        'Las Flores',
        '55100',
        'Estado de Mexico',
        'Ecatepec',
        '+52 55 1000 0002',
        NULL,
        1,
        0,
        @rol_vet_id
    ),
    (
        'Carlos Cliente Demo',
        'Carlos',
        'Cliente',
        'Demo',
        @cliente_email,
        'scrypt:32768:8:1$3uFlVDfbxZdIU24o$7114fb750fed2ca6e6912d04372f2e6970630189bf98ae3d167da6f6078990ba7a5ad0212fe8246edae0af7ecb405c7fed24b401e3f4c8c3f797987d7ecaf849',
        'Av. Demo 123, Ecatepec',
        'Av. Demo',
        '123',
        'San Pedro',
        '55200',
        'Estado de Mexico',
        'Ecatepec',
        '+52 55 1000 0003',
        NULL,
        1,
        0,
        @rol_cliente_id
    );

SET @cliente_id = (
    SELECT id FROM usuarios WHERE correo = @cliente_email LIMIT 1
);
SET @vet_id = (
    SELECT id FROM usuarios WHERE correo = @vet_email LIMIT 1
);

INSERT INTO mascotas (
    nombre,
    fecha_nacimiento,
    peso,
    raza,
    especie,
    sexo,
    datos_adicionales,
    estado,
    razon_inactivacion,
    dueno_id,
    comportamiento
) VALUES (
    @mascota_nombre,
    '2022-06-15',
    12.40,
    'Mestiza',
    'perro',
    'hembra',
    'Paciente de demostracion para consulta general.',
    'activa',
    NULL,
    @cliente_id,
    'Sociable y tranquila durante la revision.'
);

SET @mascota_id = (
    SELECT id
    FROM mascotas
    WHERE dueno_id = @cliente_id AND nombre = @mascota_nombre
    LIMIT 1
);

INSERT INTO citas (
    fecha_hora,
    motivo,
    cliente_id,
    veterinario_id,
    mascota_id,
    estado,
    cancelada
) VALUES (
    '2026-03-10 11:00:00',
    'Consulta general de demostracion',
    @cliente_id,
    @vet_id,
    @mascota_id,
    'confirmada',
    0
);

SET @cita_id = (
    SELECT id
    FROM citas
    WHERE cliente_id = @cliente_id
      AND veterinario_id = @vet_id
      AND mascota_id = @mascota_id
    ORDER BY id DESC
    LIMIT 1
);

INSERT INTO recordatorios_citas (
    cita_id,
    estado,
    enviado_en,
    confirmado,
    confirmado_en,
    token_confirmacion
) VALUES (
    @cita_id,
    'programado',
    NULL,
    0,
    NULL,
    CONCAT('demo-recordatorio-', @cita_id)
);

INSERT INTO facturacion (
    cliente_id,
    fecha_pago,
    descripcion,
    monto_total,
    descuento,
    monto_pagado,
    adeudo,
    estado,
    metodo_pago,
    observaciones
) VALUES (
    @cliente_id,
    '2026-03-10 11:45:00',
    'Consulta general de demostracion',
    450.00,
    0.00,
    450.00,
    0.00,
    'pagado',
    'tarjeta',
    'Movimiento demo generado por seed.'
);

COMMIT;
