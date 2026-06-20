namespace Monte_Carlo_Pi_Berechnung
{
    internal class Program
    {
        static void Main(string[] args)
        {
            int gesamtRunden = 0;
            int getroffeneRunden = 0;
            string vergleichsPi = Math.PI.ToString().Substring(0, 10);
            float berechnetesPi = 0;


            while (true)
            {
                Random rand = new Random();
                int x = rand.Next(-1, 1);
                int y = rand.Next(-1, 1);
                gesamtRunden++;
                if (Math.Pow(x, 2) + Math.Pow(y, 2) < 1)
                {
                    getroffeneRunden++;
                }
                berechnetesPi = 4 * getroffeneRunden / gesamtRunden;
                if(berechnetesPi.ToString().Substring(0, 10) != vergleichsPi)
                {
                    Console.WriteLine(berechnetesPi + " nach " + gesamtRunden + " getroffenen Runden mit " + getroffeneRunden + " getroffene Runden");
                    break;
                }
            }

          
        }
    }
}
