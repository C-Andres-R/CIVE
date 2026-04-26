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
  fuente_captacion ENUM('recomendacion', 'redes_sociales') DEFAULT NULL,
  fecha_registro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
  anticipacion_horas INT DEFAULT NULL,
  programado_para DATETIME DEFAULT NULL,
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
  calificacion INT DEFAULT NULL,
  conforme TINYINT(1) DEFAULT NULL,
  detalle_inconformidad VARCHAR(300) DEFAULT NULL,
  comentario TEXT DEFAULT NULL,
  fecha_programada_envio DATETIME DEFAULT NULL,
  fecha_envio DATETIME DEFAULT NULL,
  fecha_respuesta DATETIME DEFAULT NULL,
  correo_enviado TINYINT(1) NOT NULL DEFAULT 0,
  respondido TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_encuestas_cita_cliente (cita_id, cliente_id),
  KEY idx_encuestas_cliente_id (cliente_id),
  CONSTRAINT fk_encuestas_cita FOREIGN KEY (cita_id) REFERENCES citas (id) ON DELETE CASCADE,
  CONSTRAINT fk_encuestas_cliente FOREIGN KEY (cliente_id) REFERENCES usuarios (id) ON DELETE CASCADE,
  CONSTRAINT ck_encuestas_calificacion_1_5 CHECK (calificacion >= 1 AND calificacion <= 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE encuestas_preguntas (
  id INT NOT NULL AUTO_INCREMENT,
  clave VARCHAR(80) NOT NULL,
  texto VARCHAR(255) NOT NULL,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_encuestas_preguntas_clave (clave)
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

CREATE TABLE insumos_clinicos (
  id INT NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(120) NOT NULL,
  tipo_insumo ENUM('medicamento', 'vacuna') NOT NULL,
  fecha_caducidad DATE NOT NULL,
  cantidad_existencia INT NOT NULL DEFAULT 0,
  precio DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_insumos_clinicos_tipo_insumo (tipo_insumo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE consultas_medicas (
  id INT NOT NULL AUTO_INCREMENT,
  mascota_id INT NOT NULL,
  veterinario_id INT NOT NULL,
  insumo_clinico_id INT DEFAULT NULL,
  vacuna_insumo_id INT DEFAULT NULL,
  tipo_analisis_relacionado VARCHAR(120) DEFAULT NULL,
  fecha_consulta DATE NOT NULL,
  sintomas TEXT NOT NULL,
  diagnostico TEXT NOT NULL,
  tratamiento TEXT NOT NULL,
  medicamentos_administrados TEXT DEFAULT NULL,
  fecha_administracion DATE DEFAULT NULL,
  dosis VARCHAR(120) DEFAULT NULL,
  periodo_administracion VARCHAR(120) DEFAULT NULL,
  observaciones TEXT DEFAULT NULL,
  precio_consulta DECIMAL(10,2) NOT NULL DEFAULT 300.00,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_consultas_medicas_mascota_id (mascota_id),
  KEY idx_consultas_medicas_veterinario_id (veterinario_id),
  KEY idx_consultas_medicas_insumo_clinico_id (insumo_clinico_id),
  KEY idx_consultas_medicas_vacuna_insumo_id (vacuna_insumo_id),
  CONSTRAINT fk_consultas_medicas_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id) ON DELETE CASCADE,
  CONSTRAINT fk_consultas_medicas_veterinario FOREIGN KEY (veterinario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_consultas_medicas_insumo_clinico FOREIGN KEY (insumo_clinico_id) REFERENCES insumos_clinicos (id),
  CONSTRAINT fk_consultas_medicas_vacuna_insumo FOREIGN KEY (vacuna_insumo_id) REFERENCES insumos_clinicos (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE vacunas_alergias (
  id INT NOT NULL AUTO_INCREMENT,
  mascota_id INT NOT NULL,
  veterinario_id INT NOT NULL,
  insumo_clinico_id INT DEFAULT NULL,
  tipo_registro ENUM('vacuna', 'alergia') NOT NULL,
  fecha_registro DATE NOT NULL,
  nombre VARCHAR(120) NOT NULL,
  reaccion_identificada TEXT DEFAULT NULL,
  notas_adicionales TEXT DEFAULT NULL,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_vacunas_alergias_mascota_id (mascota_id),
  KEY idx_vacunas_alergias_veterinario_id (veterinario_id),
  KEY idx_vacunas_alergias_insumo_clinico_id (insumo_clinico_id),
  CONSTRAINT fk_vacunas_alergias_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id) ON DELETE CASCADE,
  CONSTRAINT fk_vacunas_alergias_veterinario FOREIGN KEY (veterinario_id) REFERENCES usuarios (id),
  CONSTRAINT fk_vacunas_alergias_insumo_clinico FOREIGN KEY (insumo_clinico_id) REFERENCES insumos_clinicos (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE analisis_clinicos (
  id INT NOT NULL AUTO_INCREMENT,
  mascota_id INT NOT NULL,
  veterinario_id INT NOT NULL,
  fecha_analisis DATE NOT NULL,
  tipo_analisis VARCHAR(120) NOT NULL,
  resultados TEXT NOT NULL,
  precio DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  documentos_adjuntos TEXT DEFAULT NULL,
  archivo_adjunto TEXT DEFAULT NULL,
  nombre_archivo VARCHAR(255) DEFAULT NULL,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_analisis_clinicos_mascota_id (mascota_id),
  KEY idx_analisis_clinicos_veterinario_id (veterinario_id),
  CONSTRAINT fk_analisis_clinicos_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id) ON DELETE CASCADE,
  CONSTRAINT fk_analisis_clinicos_veterinario FOREIGN KEY (veterinario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE seguimientos_tratamientos (
  id INT NOT NULL AUTO_INCREMENT,
  origen_tipo ENUM('cita', 'consulta', 'vacuna_alergia', 'analisis_clinico') NOT NULL,
  origen_id INT NOT NULL,
  evento_tipo ENUM('cita', 'medicamento', 'vacuna', 'analisis') NOT NULL,
  mascota_id INT NOT NULL,
  veterinario_id INT NOT NULL,
  programado_para DATETIME NOT NULL,
  descripcion VARCHAR(255) DEFAULT NULL,
  estado ENUM('programado', 'enviado') NOT NULL DEFAULT 'programado',
  enviado_en DATETIME DEFAULT NULL,
  fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_seguimiento_origen_evento (origen_tipo, origen_id, evento_tipo),
  KEY idx_seguimientos_mascota_id (mascota_id),
  KEY idx_seguimientos_veterinario_id (veterinario_id),
  CONSTRAINT fk_seguimientos_mascota FOREIGN KEY (mascota_id) REFERENCES mascotas (id) ON DELETE CASCADE,
  CONSTRAINT fk_seguimientos_veterinario FOREIGN KEY (veterinario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
