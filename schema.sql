-- Esquema de referencia para CIVE.
-- La via recomendada para construir la base sigue siendo Alembic.
-- Este archivo refleja el estado estructural vigente del proyecto.

DROP TABLE IF EXISTS documentos_mascota;
DROP TABLE IF EXISTS fotos_mascota;
DROP TABLE IF EXISTS encuestas_satisfaccion;
DROP TABLE IF EXISTS chatbot_faq;
DROP TABLE IF EXISTS facturacion;
DROP TABLE IF EXISTS recordatorios_citas;
DROP TABLE IF EXISTS citas;
DROP TABLE IF EXISTS mascotas;
DROP TABLE IF EXISTS roles_permisos;
DROP TABLE IF EXISTS usuarios;
DROP TABLE IF EXISTS permisos;
DROP TABLE IF EXISTS roles;

CREATE TABLE roles (
  id INT NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(50) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE permisos (
  id INT NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(100) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_permisos_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE usuarios (
  id INT NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(255) NOT NULL,
  nombres VARCHAR(120) DEFAULT NULL,
  apellido_paterno VARCHAR(80) DEFAULT NULL,
  apellido_materno VARCHAR(80) DEFAULT NULL,
  correo VARCHAR(255) NOT NULL,
  contrasena VARCHAR(255) NOT NULL,
  domicilio VARCHAR(255) DEFAULT NULL,
  calle VARCHAR(120) DEFAULT NULL,
  numero VARCHAR(30) DEFAULT NULL,
  colonia VARCHAR(120) DEFAULT NULL,
  codigo_postal VARCHAR(10) DEFAULT NULL,
  estado VARCHAR(80) DEFAULT NULL,
  entidad VARCHAR(80) DEFAULT NULL,
  telefono VARCHAR(20) DEFAULT NULL,
  razon_inactivacion TEXT DEFAULT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  eliminado TINYINT(1) NOT NULL DEFAULT 0,
  rol_id INT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_usuarios_correo (correo),
  KEY idx_usuarios_rol_id (rol_id),
  CONSTRAINT fk_usuarios_rol FOREIGN KEY (rol_id) REFERENCES roles (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE roles_permisos (
  rol_id INT NOT NULL,
  permiso_id INT NOT NULL,
  PRIMARY KEY (rol_id, permiso_id),
  KEY idx_roles_permisos_permiso_id (permiso_id),
  CONSTRAINT fk_roles_permisos_rol FOREIGN KEY (rol_id) REFERENCES roles (id) ON DELETE CASCADE,
  CONSTRAINT fk_roles_permisos_permiso FOREIGN KEY (permiso_id) REFERENCES permisos (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE mascotas (
  id INT NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(100) NOT NULL,
  fecha_nacimiento DATE NOT NULL,
  peso FLOAT DEFAULT NULL,
  raza VARCHAR(100) DEFAULT NULL,
  especie ENUM('perro', 'gato', 'otro') NOT NULL,
  sexo ENUM('macho', 'hembra') NOT NULL,
  datos_adicionales TEXT DEFAULT NULL,
  estado ENUM('activa', 'inactiva') NOT NULL DEFAULT 'activa',
  razon_inactivacion TEXT DEFAULT NULL,
  dueno_id INT NOT NULL,
  comportamiento TEXT DEFAULT NULL,
  fecha_registro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_mascotas_dueno_id (dueno_id),
  CONSTRAINT fk_mascotas_dueno FOREIGN KEY (dueno_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE citas (
  id INT NOT NULL AUTO_INCREMENT,
  fecha_hora DATETIME NOT NULL,
  motivo TEXT DEFAULT NULL,
  cliente_id INT NOT NULL,
  veterinario_id INT NOT NULL,
  mascota_id INT NOT NULL,
  estado ENUM('pendiente', 'confirmada', 'cancelada') NOT NULL DEFAULT 'pendiente',
  cancelada TINYINT(1) NOT NULL DEFAULT 0,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_citas_cliente_id (cliente_id),
  KEY idx_citas_veterinario_id (veterinario_id),
  KEY idx_citas_mascota_id (mascota_id),
  CONSTRAINT fk_citas_cliente FOREIGN KEY (cliente_id) REFERENCES usuarios (id),
  CONSTRAINT fk_citas_veterinario FOREIGN KEY (veterinario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_citas_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE recordatorios_citas (
  id INT NOT NULL AUTO_INCREMENT,
  cita_id INT NOT NULL,
  estado ENUM('programado', 'enviado') NOT NULL DEFAULT 'programado',
  enviado_en DATETIME DEFAULT NULL,
  confirmado TINYINT(1) NOT NULL DEFAULT 0,
  confirmado_en DATETIME DEFAULT NULL,
  token_confirmacion VARCHAR(128) DEFAULT NULL,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_recordatorios_cita_id (cita_id),
  UNIQUE KEY uq_recordatorios_token_confirmacion (token_confirmacion),
  CONSTRAINT fk_recordatorios_cita FOREIGN KEY (cita_id) REFERENCES citas (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE facturacion (
  id INT NOT NULL AUTO_INCREMENT,
  cliente_id INT NOT NULL,
  fecha_pago DATETIME NOT NULL,
  descripcion TEXT DEFAULT NULL,
  monto_total DECIMAL(10,2) NOT NULL,
  descuento DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  monto_pagado DECIMAL(10,2) NOT NULL,
  adeudo DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  estado ENUM('pagado', 'pendiente', 'parcial') NOT NULL DEFAULT 'pendiente',
  metodo_pago VARCHAR(50) NOT NULL,
  observaciones TEXT DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_facturacion_cliente_id (cliente_id),
  CONSTRAINT fk_facturacion_cliente FOREIGN KEY (cliente_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chatbot_faq (
  id INT NOT NULL AUTO_INCREMENT,
  pregunta VARCHAR(255) NOT NULL,
  respuesta TEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_chatbot_faq_pregunta (pregunta)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE encuestas_satisfaccion (
  id INT NOT NULL AUTO_INCREMENT,
  cita_id INT NOT NULL,
  cliente_id INT NOT NULL,
  calificacion INT NOT NULL,
  comentario TEXT DEFAULT NULL,
  fecha_envio DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  respondido TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_encuestas_cita_cliente (cita_id, cliente_id),
  KEY idx_encuestas_cliente_id (cliente_id),
  CONSTRAINT fk_encuestas_cita FOREIGN KEY (cita_id) REFERENCES citas (id) ON DELETE CASCADE,
  CONSTRAINT fk_encuestas_cliente FOREIGN KEY (cliente_id) REFERENCES usuarios (id) ON DELETE CASCADE,
  CONSTRAINT ck_encuestas_calificacion_1_5 CHECK (calificacion >= 1 AND calificacion <= 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE fotos_mascota (
  id INT NOT NULL AUTO_INCREMENT,
  mascota_id INT NOT NULL,
  url_foto TEXT NOT NULL,
  nombre_archivo VARCHAR(255) DEFAULT NULL,
  fecha_subida DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_fotos_mascota_id (mascota_id),
  CONSTRAINT fk_fotos_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE documentos_mascota (
  id INT NOT NULL AUTO_INCREMENT,
  mascota_id INT NOT NULL,
  archivo TEXT NOT NULL,
  nombre_archivo VARCHAR(255) DEFAULT NULL,
  tipo_documento VARCHAR(100) DEFAULT NULL,
  fecha_subida DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_documentos_mascota_id (mascota_id),
  CONSTRAINT fk_documentos_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
