from decimal import Decimal

from django.core.management.base import BaseCommand

from orders.models import Category, Product, ProductExtra


class Command(BaseCommand):
    help = "Crea o actualiza las categorías y productos de ejemplo de la carta."

    def handle(self, *args, **options):
        catalog = {
            "Hamburguesas": [
                ("La Clásica", "Carne a la parrilla, queso, lechuga y salsa de la casa.", "18900", True),
                ("Doble Esquina", "Doble carne, cheddar, cebolla caramelizada.", "24900", True),
                ("Pollo Crocante", "Pollo apanado, repollo fresco y mayonesa cítrica.", "20900", False),
            ],
            "Perros": [
                ("Perro clásico", "Salchicha, pan suave, papas ripio y salsas.", "12900", False),
                ("Perro especial", "Salchicha, queso, tocineta, papas ripio y salsas.", "17900", True),
            ],
            "Salchipapas": [
                ("Salchipapa personal", "Papas crocantes, salchicha y salsas de la casa.", "16900", False),
                ("Salchipapa especial", "Papas, salchicha, pollo, queso y salsas.", "23900", True),
            ],
            "Asados": [
                ("Churrasco", "Carne a la parrilla con papa y ensalada.", "32900", True),
            ],
            "Patacones": [
                ("Patacón con todo", "Patacón crocante con carne, queso y salsas.", "18900", False),
            ],
            "Para acompañar": [
                ("Papas de la casa", "Papas doradas con sal de romero.", "8900", False),
                ("Aros de cebolla", "Crujientes, recién hechos.", "9900", False),
            ],
            "Bebidas": [
                ("Limonada natural", "Limón fresco, hielo y un toque de hierbabuena.", "6500", False),
                ("Gaseosa", "Botella personal fría.", "5000", False),
            ],
        }
        for sort_order, (category_name, products) in enumerate(catalog.items()):
            category, _ = Category.objects.get_or_create(name=category_name)
            category.sort_order = sort_order
            category.active = True
            category.save(update_fields=["sort_order", "active"])
            for name, description, price, featured in products:
                product = Product.objects.filter(name=name).order_by("id").first()
                if product is None:
                    product = Product.objects.create(category=category, name=name, **{
                    "description": description, "price": Decimal(price), "featured": featured,
                    "stock_tracked": "bebida" in category_name.casefold(),
                })
                elif product.category_id != category.id:
                    product.category = category
                    product.save(update_fields=["category"])
                if "bebida" in category_name.casefold() and not product.stock_tracked:
                    product.stock_tracked = True
                    product.save(update_fields=["stock_tracked"])

        ProductExtra.objects.filter(
            product__name="La Clásica",
            name__in=("Doble carne", "Queso extra", "Tocineta"),
        ).delete()
        Category.objects.filter(name="Favoritos", products__isnull=True).delete()
        self.stdout.write(self.style.SUCCESS(
            "Carta actualizada. Los precios de productos nuevos son valores de ejemplo editables en COP."
        ))