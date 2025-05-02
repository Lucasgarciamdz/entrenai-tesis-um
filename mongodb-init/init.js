// Este script inicializa la base de datos MongoDB
db = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);

// Crear una colección inicial (necesario para que se cree la base de datos)
db.createCollection('documentos');

// Insertar un documento inicial
db.documentos.insertOne({
  "nombre": "documento_inicial",
  "descripcion": "Este documento se crea al inicializar la base de datos",
  "fecha_creacion": new Date()
}); 

// Crear usuario administrador para la base de datos
db.createUser({
  user: process.env.MONGODB_USERNAME || "admin",
  pwd: process.env.MONGODB_PASSWORD || "password",
  roles: [
    { role: "dbOwner", db: process.env.MONGO_INITDB_DATABASE },
    { role: "readWrite", db: process.env.MONGO_INITDB_DATABASE }
  ]
});